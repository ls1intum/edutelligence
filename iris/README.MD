# Pyris V2
## With local environment

### Setup
 - Check python version: `python --version` (should be 3.12)
 - Install packages: `pip install -r requirements.txt`

### Run server
 - Run server: 
   ```[bash]
     APPLICATION_YML_PATH=<path-to-your-application-yml-file> LLM_CONFIG_PATH=<path-to-your-llm-config-yml> uvicorn app.main:app --reload
    ```
 - Access API docs: http://localhost:8000/docs

## With docker
TBD