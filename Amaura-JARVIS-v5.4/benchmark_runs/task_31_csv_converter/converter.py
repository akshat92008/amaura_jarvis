import json
import csv
from io import StringIO

def csv_to_json(csv_string: str) -> str:
    """Convert CSV string to JSON string."""
    reader = csv.DictReader(StringIO(csv_string))
    return json.dumps(list(reader), indent=2)

def json_to_csv(json_string: str) -> str:
    """Convert JSON string to CSV string."""
    data = json.loads(json_string)
    if not data:
        return ""
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    
    return output.getvalue()

if __name__ == "__main__":
    # Example usage
    csv_data = """name,age,city\nAlice,30,New York\nBob,25,Los Angeles\nCharlie,35,Chicago"""
    json_data = csv_to_json(csv_data)
    print("CSV to JSON:")
    print(json_data)
    
    csv_data_converted = json_to_csv(json_data)
    print("\nJSON to CSV:")
    print(csv_data_converted)
