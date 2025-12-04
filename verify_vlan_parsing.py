import json

def test_vlan_parsing():
    print("Testing VLAN Parsing Logic (JSON)...")

    # Mock Data
    node = 227
    interface = "eth1/14"
    
    # Case 1: Direct Path Match
    json_direct = {
        "imdata": [
            {
                "fvRsPathAtt": {
                    "attributes": {
                        "tDn": "topology/pod-1/paths-227/pathep-[eth1/14]",
                        "encap": "vlan-3149"
                    }
                }
            }
        ]
    }
    vlan, path_type, path_dn, domains = parse_fvRsPathAtt(json_direct, node, interface)
    print(f"Case 1 (Direct): Expected (vlan-3149, Direct) -> Got ({vlan}, {path_type})")
    assert vlan == "vlan-3149"
    assert path_type == "Direct"

    # Case 2: VPC Path Match
    json_vpc = {
        "imdata": [
            {
                "fvRsPathAtt": {
                    "attributes": {
                        "tDn": "topology/pod-1/protpaths-225-226/pathep-[Leaf-225-226_PolGrp_Port14]",
                        "encap": "vlan-401"
                    }
                }
            }
        ]
    }
    # Test with node 225 (part of VPC)
    vlan, path_type, path_dn, domains = parse_fvRsPathAtt(json_vpc, 225, interface)
    print(f"Case 2 (VPC): Expected (vlan-401, VPC) -> Got ({vlan}, {path_type})")
    assert vlan == "vlan-401"
    assert path_type == "VPC"

    # Case 3: No Match (Wrong Node) + Physical Domain
    json_nomatch = {
        "imdata": [
            {
                "fvRsPathAtt": {
                    "attributes": {
                        "tDn": "topology/pod-1/paths-293/pathep-[eth1/14]", # Wrong node
                        "encap": "vlan-3149"
                    }
                }
            },
            {
                "fvRsDomAtt": {
                    "attributes": {
                        "tDn": "uni/phys-MyPhysDom"
                    }
                }
            }
        ]
    }
    vlan, path_type, path_dn, domains = parse_fvRsPathAtt(json_nomatch, node, interface)
    print(f"Case 3 (Wrong Node + PhysDom): Expected (Not Found (Node Mismatch), Partial Match, MyPhysDom) -> Got ({vlan}, {path_type}, {domains})")
    assert vlan == "Not Found (Node Mismatch)"
    assert path_type == "Partial Match"
    assert "MyPhysDom" in domains

    # Case 4: VMM Domain (No Static Path)
    json_vmm = {
        "imdata": [
            {
                "fvRsDomAtt": {
                    "attributes": {
                        "tDn": "uni/vmmp-VMware/dom-MyVMMDomain"
                    }
                }
            }
        ]
    }
    vlan, path_type, _, domains = parse_fvRsPathAtt(json_vmm, node, interface)
    print(f"Case 4 (VMM): Expected (Dynamic (VMM), VMM Domain, MyVMMDomain) -> Got ({vlan}, {path_type}, {domains})")
    assert vlan == "Dynamic (VMM)"
    assert path_type == "VMM Domain"
    assert "MyVMMDomain" in domains

    # Case 5: Partial Match (Node Mismatch)
    # Requesting Node 293, but path is on Node 227
    node_mismatch = 293
    json_partial = {
        "imdata": [
            {
                "fvRsPathAtt": {
                    "attributes": {
                        "tDn": "topology/pod-1/paths-227/pathep-[eth1/14]",
                        "encap": "vlan-3149"
                    }
                }
            }
        ]
    }
    vlan, path_type, path_dn, domains = parse_fvRsPathAtt(json_partial, node_mismatch, interface)
    print(f"Case 5 (Partial): Expected (Not Found (Node Mismatch), Partial Match) -> Got ({vlan}, {path_type})")
    assert vlan == "Not Found (Node Mismatch)"
    assert path_type == "Partial Match"
    assert "Node 227" in path_dn

    print("All tests passed!")

def parse_fvRsPathAtt(data, node, interface):
    # This is a copy of the logic inside get_epg_vlan for testing purposes
    
    # Extract Domains
    domains = []
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

    # 1. Check for Static Paths
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
                            nodes_str = part[10:]
                            vpc_nodes = nodes_str.split('-')
                            if str(node) in vpc_nodes:
                                return encap, "VPC", t_dn, domains_str
                except Exception:
                    pass
            
            # Check for Partial Match
            if target_direct_suffix in t_dn:
                found_node = "Unknown"
                if "paths-" in t_dn:
                    try:
                        found_node = t_dn.split('paths-')[1].split('/')[0]
                    except: pass
                elif "protpaths-" in t_dn:
                    try:
                        found_node = t_dn.split('protpaths-')[1].split('/')[0]
                    except: pass
                partial_matches.append(f"Node {found_node}")

    # 2. Check for VMM
    is_vmm = False
    for item in data.get('imdata', []):
        if 'fvRsDomAtt' in item:
            t_dn = item['fvRsDomAtt']['attributes'].get('tDn', '')
            if 'vmmp-' in t_dn:
                is_vmm = True
                break
    
    if is_vmm:
        return "Dynamic (VMM)", "VMM Domain", "N/A", domains_str

    if partial_matches:
        unique_partials = list(set(partial_matches))
        return "Not Found (Node Mismatch)", "Partial Match", f"Found on: {', '.join(unique_partials)}", domains_str

    return "Not Found", "None", "No matching path", domains_str

if __name__ == "__main__":
    test_vlan_parsing()

if __name__ == "__main__":
    test_vlan_parsing()
