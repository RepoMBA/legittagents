#!/usr/bin/env python3
"""
Script to update all files with the correct server URL from config.py
"""

import re
from config import SERVER_URL

def update_frontend():
    """Update frontend.html with the server URL from config"""
    
    # Read the current frontend.html
    with open('frontend.html', 'r') as f:
        content = f.read()
    
    # Replace the SERVER_URL in the JavaScript
    pattern = r"const SERVER_URL = '[^']*';"
    replacement = f"const SERVER_URL = '{SERVER_URL}';"
    
    if re.search(pattern, content):
        content = re.sub(pattern, replacement, content)
        print(f"Updated frontend.html SERVER_URL to: {SERVER_URL}")
    else:
        print("Warning: SERVER_URL not found in frontend.html")
        return False
    
    # Write back to file
    with open('frontend.html', 'w') as f:
        f.write(content)
    
    return True

def update_script():
    """Update script.sh with the server URL from config"""
    
    # Read the current script.sh
    with open('script.sh', 'r') as f:
        content = f.read()
    
    # Replace the API_URL in the script
    pattern = r'API_URL="[^"]*"'
    replacement = f'API_URL="{SERVER_URL}"'
    
    if re.search(pattern, content):
        content = re.sub(pattern, replacement, content)
        print(f"Updated script.sh API_URL to: {SERVER_URL}")
    else:
        print("Warning: API_URL not found in script.sh")
        return False
    
    # Write back to file
    with open('script.sh', 'w') as f:
        f.write(content)
    
    return True

def main():
    """Update all files with the correct server URL"""
    print(f"Updating all files to use server URL: {SERVER_URL}")
    
    success = True
    success &= update_frontend()
    success &= update_script()
    
    if success:
        print("\n✅ All files updated successfully!")
        print(f"Server URL set to: {SERVER_URL}")
        print("\nTo change the server URL, edit config.py and run this script again.")
    else:
        print("\n❌ Some files could not be updated. Please check the warnings above.")

if __name__ == "__main__":
    main() 