# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resouce management, policy-based model selection, scheduling, and monitoring.

# Setup

## Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

## Installation

### Poetry

Install Poetry, if you haven't already:

```bash
pip install poetry
```

Ensure that you are using poetry version 2.0.0 or higher.

```bash
poetry --version
```

If you have poetry < 2.0.0 installed, please run

```bash
poetry self update
```

#### Dependencies

Activate the virtual environment and install the dependencies:

```bash
poetry env activate
poetry install
```

## Running the Service
To deploy Logos locally or on a server:

1. Clone the repository:

   ```bash
   git clone https://github.com/ls1intum/edutelligence/
   
2. Insert initial Provider Configuration

   In docker-compose.yml, adjust the environment section of the logos-server 
   container to specify the initial LLM provider that Logos should connect to after startup.

   Example Configuration:
      ```
       environment:
         PROVIDER_NAME: azure
         BASE_URL: https://ase-se01.openai.azure.com/openai/deployments/
      ```

3. Build and Run Logos

   Now go to the root-directory of Edutelligence and execute the following commands:
   
   ```
   docker compose -f ./logos/docker-compose.yaml build
   ```
   
   and afterward
   
   ```
   docker compose -f ./logos/docker-compose.yaml up
   ```

   After startup, Logos will print your initial root key in the logs—save this, as it is required for first login.

4. Access Web-UI

   Once running, the Logos UI is accessible at:
   ```
   https://logos.ase.cit.tum.de:8080/
   ```
   You can log in using the root key provided at startup.

5. Explore the API

   A full overview of available endpoints can be found at: https://logos.ase.cit.tum.de:8080/docs