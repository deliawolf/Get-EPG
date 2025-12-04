import requests
import pandas as pd
import xml.etree.ElementTree as ET
import urllib3
import getpass
import os
import time

# Disable warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def login_apic(apic_ip, username, password):
    """Logs into the APIC and returns the session cookie."""
    url = f"https://{apic_ip}/api/aaaLogin.json"
    payload = {
        "aaaUser": {
            "attributes": {
                "name": username,
                "pwd": password
            }
        }
    }
    try:
        response = requests.post(url, json=payload, verify=False, timeout=10)
        response.raise_for_status()
        token = response.json()['imdata'][0]['aaaLogin']['attributes']['token']
        return token
    except Exception as e:
        print(f"Login failed: {e}")
        return None

def get_epgs_for_interface(apic_ip, token, node, interface):
    """Queries the APIC for EPGs on a specific interface."""
    # Format interface for URL (e.g., eth1/10 -> eth1/10, but in URL it is usually eth1/10 inside brackets)
    # The user example: sys/phys-[eth1/43]
    
    url = f"https://{apic_ip}/api/node/mo/topology/pod-1/node-{node}/sys/phys-[{interface}].xml?rsp-subtree-include=full-deployment&target-node=all&target-path=l1EthIfToEPg"
    
    headers = {
        "Cookie": f"APIC-cookie={token}"
    }
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error querying Node {node} Interface {interface}: {e}")
        return None

def parse_epgs(xml_content):
    """Parses the XML content to extract EPG information."""
    epgs = []
    try:
        root = ET.fromstring(xml_content)
        # Namespace handling might be needed if the XML has namespaces, but the example doesn't show explicit xmlns in the root for the attributes we care about.
        # We look for pconsResourceCtx with ctxClass="fvAEPg"
        
        for pcons in root.findall(".//pconsResourceCtx[@ctxClass='fvAEPg']"):
            ctx_dn = pcons.get('ctxDn')
            if ctx_dn:
                # Example ctxDn: uni/tn-DC-SHARED-SVC/ap-ANP-SERVICES-SHARED-SVC/epg-EPG_172.18.9.0x24
                parts = ctx_dn.split('/')
                tenant = ""
                app_profile = ""
                epg_name = ""
                
                for part in parts:
                    if part.startswith('tn-'):
                        tenant = part[3:]
                    elif part.startswith('ap-'):
                        app_profile = part[3:]
                    elif part.startswith('epg-'):
                        epg_name = part[4:]
                
                epgs.append({
                    'Tenant': tenant,
                    'AppProfile': app_profile,
                    'EPG': epg_name,
                    'DN': ctx_dn
                })
    except Exception as e:
        print(f"Error parsing XML: {e}")
    return epgs

def get_epg_vlan(apic_ip, token, epg_dn, node, interface):
    """
    Queries the EPG for its fvRsPathAtt children and finds the VLAN for the given node/interface.
    Returns (vlan, path_type, path_dn, domains_str)
    """
    # Query for both static paths (fvRsPathAtt) and VMM domains (fvRsDomAtt) using JSON
    # Explicitly ask for these classes and increase page size to ensure we get all paths
    url = f"https://{apic_ip}/api/node/mo/{epg_dn}.json?query-target=children&target-subtree-class=fvRsPathAtt,fvRsDomAtt&page-size=10000"
    headers = {
        "Cookie": f"APIC-cookie={token}"
    }
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract Domains
        domains = []
        # JSON structure: {"imdata": [{"fvRsDomAtt": {"attributes": {...}}}, ...]}
        for item in data.get('imdata', []):
            if 'fvRsDomAtt' in item:
                t_dn = item['fvRsDomAtt']['attributes'].get('tDn')
                if t_dn:
                    parts = t_dn.split('/')
                    if parts:
                        last_part = parts[-1]
                        if '-' in last_part:
                            domains.append(last_part.split('-', 1)[1])
                        else:
                            domains.append(last_part)
        domains_str = ", ".join(domains)

        # 1. Check for Static Paths (fvRsPathAtt)
        # Normalize interface: ensure 'eth' prefix, remove 'Ethernet' if present, STRIP whitespace
        clean_interface = str(interface).strip()
        norm_interface = clean_interface.replace("Ethernet", "eth")
        target_direct_suffix = f"pathep-[{norm_interface}]"
        
        partial_matches = []

        for item in data.get('imdata', []):
            if 'fvRsPathAtt' in item:
                attrs = item['fvRsPathAtt']['attributes']
                t_dn = attrs.get('tDn')
                encap = attrs.get('encap')
                
                if not t_dn:
                    continue
                
                # Check for Direct Match
                if f"paths-{node}/" in t_dn and target_direct_suffix in t_dn:
                    return encap, "Direct", t_dn, domains_str
                
                # Check for VPC Match
                if "protpaths-" in t_dn:
                    try:
                        parts = t_dn.split('/')
                        for part in parts:
                            if part.startswith('protpaths-'):
                                nodes_str = part[10:] # 225-226
                                vpc_nodes = nodes_str.split('-')
                                if str(node) in vpc_nodes:
                                    return encap, "VPC", t_dn, domains_str
                    except Exception:
                        pass
                
                # Check for Partial Match (Interface matches, but Node doesn't)
                if target_direct_suffix in t_dn:
                    # Extract the node from the path to show the user
                    found_node = "Unknown"
                    if "paths-" in t_dn:
                        # .../paths-227/...
                        try:
                            found_node = t_dn.split('paths-')[1].split('/')[0]
                        except: pass
                    elif "protpaths-" in t_dn:
                        # .../protpaths-225-226/...
                        try:
                            found_node = t_dn.split('protpaths-')[1].split('/')[0]
                        except: pass
                    
                    partial_matches.append(f"Node {found_node}")

        # 2. If no static path matched, check if it's a VMM Domain
        is_vmm = False
        for item in data.get('imdata', []):
            if 'fvRsDomAtt' in item:
                t_dn = item['fvRsDomAtt']['attributes'].get('tDn', '')
                if 'vmmp-' in t_dn:
                    is_vmm = True
                    break
        
        if is_vmm:
            # Even if VMM, if we found partial matches, it might be useful to know.
            # But usually VMM is the fallback. 
            return "Dynamic (VMM)", "VMM Domain", "N/A", domains_str

        # 3. If neither, check if we had partial matches
        if partial_matches:
            unique_partials = list(set(partial_matches))
            return "Not Found (Node Mismatch)", "Partial Match", f"Found on: {', '.join(unique_partials)}", domains_str

        return "Not Found", "None", "No matching path", domains_str

    except Exception as e:
        print(f"Error querying VLAN for {epg_dn}: {e}")
        return "Error", "Error", str(e), ""

def main():
    print("ACI EPG Discovery Tool")
    
    # Configuration
    input_file = 'input_interfaces.xlsx'
    output_file = 'output_epgs.xlsx'
    
    # Get credentials
    apic_ip = input("Enter APIC IP: ")
    username = input("Enter Username: ")
    password = getpass.getpass("Enter Password: ")
    
    # Login
    print("Logging in...")
    token = login_apic(apic_ip, username, password)
    if not token:
        return

    print("Login successful.")
    
    # Read input
    try:
        df_input = pd.read_excel(input_file)
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
        return

    all_results = []

    print(f"Processing {len(df_input)} interfaces...")
    
    for index, row in df_input.iterrows():
        node = row['Node']
        interface = row['Interface']
        
        print(f"Checking Node {node} Interface {interface}...")
        
        xml_content = get_epgs_for_interface(apic_ip, token, node, interface)
        
        if xml_content:
            epgs = parse_epgs(xml_content)
            if epgs:
                print(f"  Found {len(epgs)} EPGs. Querying VLANs...")
                for epg in epgs:
                    epg['Node'] = node
                    epg['Interface'] = interface
                    
                    # Query VLAN
                    vlan, path_type, path_dn, domains = get_epg_vlan(apic_ip, token, epg['DN'], node, interface)
                    epg['VLAN'] = vlan
                    epg['PathType'] = path_type
                    epg['PathDN'] = path_dn
                    epg['Domains'] = domains
                    
                    all_results.append(epg)
            else:
                print(f"  No EPGs found or parsing error.")
        
        # Rate limiting to be safe
        time.sleep(0.1)

    # Save results
    if all_results:
        df_output = pd.DataFrame(all_results)
        # Reorder columns
        cols = ['Node', 'Interface', 'Tenant', 'AppProfile', 'EPG', 'VLAN', 'PathType', 'DN', 'PathDN', 'Domains']
        # Ensure all columns exist
        for col in cols:
            if col not in df_output.columns:
                df_output[col] = ""
                
        df_output = df_output[cols]
        df_output.to_excel(output_file, index=False)
        print(f"Results saved to {output_file}")
    else:
        print("No results to save.")

if __name__ == "__main__":
    main()
