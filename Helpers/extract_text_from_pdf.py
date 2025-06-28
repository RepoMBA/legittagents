import fitz  # PyMuPDF
import re
import json

FLIGHT_CODES = './Database/flightCode.json'
PDF_PATH = '/Users/shresthkansal/LegittAI/legittagents/Database/To_Be_Processed/9H-SLD/9H-SLD004311.pdf'

with open(FLIGHT_CODES) as f:
    code_map = json.load(f)

sorted_keys = sorted(code_map.keys(), key=len, reverse=True)

def replace_prefix(flight_code: str) -> str:
    """If flight_code starts with one of our keys, replace that prefix."""
    for key in sorted_keys:
        if flight_code.upper().startswith(key):
            # found a match—build new string:
            #   replacement + the rest of the original code
            return code_map[key] + flight_code[len(key):]
    # no match → just return original
    return flight_code

def extract_text(pdf_path):
    """Extract all text from the PDF (no OCR)."""
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

def parse_fields(text):
    """
    Parse required fields from the extracted text.
    Adjust regex patterns as needed for your PDF format.
    """
    patterns = {
        'EnquiryNo':  r'$^',# not to be in pushed version
        'Date': r'Departure\s*([^\s]+)',
        'FlightNumber': r'Flight Date\s*([A-Z0-9]{3,10})',
        'Registration': r'(?m)^([A-Z0-9-]+)\s*\r?\nReg$',
        'Dep': r'Departure\s*(?:[0-9]{2}-[A-Za-z]{3}-[0-9]{2})\s*([A-Z]{3})\s*/',
        'Arr': r'Arrival\s*\r?\n[0-9]{2}-[A-Za-z]{3}-[0-9]{2}\s*\r?\n(?:.*\r?\n)?([A-Z]{3})\s*/',
        'STD': r'$^',  # leave empty
        'STA': r'$^',  # leave empty
        'ETA': r'$^',  # leave empty
        'ETD': r'$^',  # leave empty
        'ATD': r'OFF BLOCKS\s*([0-9]{2}:[0-9]{2})',
        'ATA': r'ON BLOCKS\s*([0-9]{2}:[0-9]{2})',
        'TO': r'AIRBORNE\s*([0-9]{2}:[0-9]{2})',        
        'LDG': r'LANDED\s*([0-9]{2}:[0-9]{2})',
        'FuelBurn': r'$^',
        'DelayCode':     r'Delays:\s*[0-9]{2}:[0-9]{2},\s*([0-9/A-Z]+)',
        'DelayDuration': r'Delays:\s*([0-9]{2}:[0-9]{2})',
        'DelayReason': r'$^',
        'Pax': r'$^',
        'Payload': r'$^',
        'ReasonOfCancellation': r'$^',
        'Rotation': r'$^',
    }

    data = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            # Some patterns have two groups; pick the one that matched
            val = next((g for g in match.groups() if g), "").strip()
        else:
            val = None
        data[field] = val
    
    m = re.search(r'Total\s+[0-9]+\s+([0-9]+)\s+([0-9]+)', text)
    if m:
        second = int(m.group(1))   # 11220
        third  = int(m.group(2))   # 5710
        fuel_burned = second - third
        data['FuelBurn'] = fuel_burned

    data['FlightNumber'] = replace_prefix(data['FlightNumber'])
    


    return data

def data_retriever(pdf_path):
    raw_text = extract_text(pdf_path)
    # print(raw_text[:900])
    result = parse_fields(raw_text)
    return result
    

def main(pdf_path):
    raw_text = extract_text(pdf_path)
    print(raw_text[:1200])
    result = parse_fields(raw_text)
    print("Extracted Fields Dictionary:")
    for key, val in result.items():
        print(f"{key}: {val}")

if __name__ == "__main__":
    main(PDF_PATH)
