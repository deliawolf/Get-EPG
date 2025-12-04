import pandas as pd
import os

def test_excel_generation():
    output_file = 'test_output.xlsx'
    
    # Dummy results mimicking the structure in aci_epg_discovery.py
    all_results = [
        {
            'Node': '225',
            'Interface': 'eth1/10',
            'Tenant': 'Test-Tenant',
            'AppProfile': 'Test-AP',
            'EPG': 'Test-EPG',
            'VLAN': 'vlan-100',
            'PathType': 'VPC',
            'PathDN': 'topology/pod-1/protpaths-225-226/pathep-[...]',
            'Domains': 'phys'
        }
    ]
    
    # Logic from aci_epg_discovery.py
    if all_results:
        df_output = pd.DataFrame(all_results)
        # Reorder columns - Added PathType and PathDN as requested
        cols = ['Node', 'Interface', 'Tenant', 'AppProfile', 'EPG', 'PathType', 'PathDN']
        # Ensure all columns exist
        for col in cols:
            if col not in df_output.columns:
                df_output[col] = ""
                
        df_output = df_output[cols]
        df_output.to_excel(output_file, index=False)
        print(f"Results saved to {output_file}")
        
        # Verify columns
        df_read = pd.read_excel(output_file)
        print("Columns in generated file:", df_read.columns.tolist())
        
        expected_cols = ['Node', 'Interface', 'Tenant', 'AppProfile', 'EPG', 'PathType', 'PathDN']
        if list(df_read.columns) == expected_cols:
            print("SUCCESS: Columns match expected output.")
        else:
            print("FAILURE: Columns do not match.")
            print(f"Expected: {expected_cols}")
            print(f"Got: {list(df_read.columns)}")

if __name__ == "__main__":
    test_excel_generation()
