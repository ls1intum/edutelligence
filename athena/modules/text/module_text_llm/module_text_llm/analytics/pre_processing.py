import json

def pre_processing(data):
    # data = json.loads(data)
    
    results = []
    for result in data['data']:
        results.append(result)
    return results        
    # return json.dumps(data)
