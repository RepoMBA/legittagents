import fitz  # PyMuPDF
import re
import argparse

def extract_text(pdf_path):
    """Extract all text from the PDF (no OCR)."""
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()  # type: ignore
    return text

def parse_fields(text):
    """
    Parse required fields from the extracted text.
    Adjust regex patterns as needed for your PDF format.
    """
    patterns = {
        'EnquiryNo': r'Model\s*([0-9]{4,8})',
        'Date': r'TechLog No\.\s*([^\s]+)',
        'FlightNumber': r'Flight Date\s*([A-Z0-9]{3,10})',
        'Registration': r'(?m)^([A-Z0-9-]+)\s*\r?\nReg$',
        'Dep': r'Departure\s*(?:[0-9]{2}-[A-Za-z]{3}-[0-9]{2})\s*([A-Z]{3})\s*/',
        'Arr': r'Arrival\s*\r?\n[0-9]{2}-[A-Za-z]{3}-[0-9]{2}\s*\r?\n.*\r?\n([A-Z]{3})\s*/',
        'STD': r'OFF BLOCKS\s*([0-9]{2}:[0-9]{2})',
        'STA': r'ON BLOCKS\s*([0-9]{2}:[0-9]{2})',
        'ETD': r'$^',  # leave empty
        'ETA': r'$^',  # leave empty
        'ATD': r'AIRBORNE\s*([0-9]{2}:[0-9]{2})',
        'ATA': r'LANDED\s*([0-9]{2}:[0-9]{2})',
        'FuelBurn': r'Fuel Burn[:\s]*([0-9]+)',
        'DelayCode': r'$^',
        'Pax': r'$^',
        'Payload': r'Payload[:\s]*([0-9]+)',
        'ReasonOfCancellation': r'$^',
        'Rotation': r'Rotation[:\s]*(.+)',
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

    data["EnquiryNo"] = "ENQ"+str(data["EnquiryNo"][1:])

    return data

def data_retriever(pdf_path):
    raw_text = extract_text(pdf_path)
    # print(raw_text[:900])
    result = parse_fields(raw_text)
    return result

def main(pdf_path):
    raw_text = extract_text(pdf_path)
    result = parse_fields(raw_text)
    print("Extracted Fields Dictionary:")
    for key, val in result.items():
        print(f"{key}: {val}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract text from a PDF file.')
    parser.add_argument('pdf_path', type=str, help='The path to the PDF file.')
    args = parser.parse_args()
    main(args.pdf_path)