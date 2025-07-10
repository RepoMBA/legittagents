#!/usr/bin/env python3
"""
Script to generate frontend.html with the correct server URL from config.py
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
        print(f"Updated SERVER_URL to: {SERVER_URL}")
    else:
        print("Warning: SERVER_URL not found in frontend.html")
        return False
    
    # Write back to file
    with open('frontend.html', 'w') as f:
        f.write(content)
    
    print("frontend.html updated successfully!")
    return True

if __name__ == "__main__":
    update_frontend() 