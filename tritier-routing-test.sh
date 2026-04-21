import os
import requests
import time

# Define the test cases
test_cases = [
    {"input": "hi", "expected_route": "cloud-middle"},
    {"input": "[priv] hello", "expected_route": "local-private"},
    {"input": "2+2", "expected_route": "cloud-middle"},
    {"input": "Explain the concept of quantum entanglement", "expected_route": "cloud-heavy"},
    {"input": "How do I implement a neural network in Python?", "expected_route": "cloud-heavy"},
    {"input": "", "expected_route": "cloud-middle"},  # or handle as an error
]

# Define the API endpoint and authentication
api_endpoint = "http://localhost:4000/v1/chat/completions"
api_key = os.environ.get('TOGETHER_API_KEY')

# Define the logging endpoint
logging_endpoint = "http://localhost:4000/logs"

# Run the tests
for test_case in test_cases:
    input_text = test_case["input"]
    expected_route = test_case["expected_route"]

    # Send the input to the API
    response = requests.post(api_endpoint, json={"model": "cloud-heavy", "messages": [{"role": "user", "content": input_text}]}, headers={"Authorization": f"Bearer {api_key}"})

    # Check the logs to verify the routing decision
    log_response = requests.get(logging_endpoint)
    log_data = log_response.json()

    # Verify the routing decision
    if log_data["route"] == expected_route:
        print(f"Test passed: {input_text} was routed to {expected_route}")
    else:
        print(f"Test failed: {input_text} was routed to {log_data['route']} instead of {expected_route}")

    # Wait a bit before sending the next test
    time.sleep(1)
