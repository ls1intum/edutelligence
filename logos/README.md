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
   Inside `docker-compose.yml` change the environment inside the logos-server-container to a provider of your choice.
   This is used to provide an initial provider logos can communicate with to serve as proxy directly
   after startup. 

   Insert the base-url of your provider and its name, e.g.:
   ```
    environment:
      PROVIDER_NAME: azure
      BASE_URL: https://ase-se01.openai.azure.com/openai/deployments/
   ```

3. Build and Run Logos

   Now go to the root-directory of Edutelligence and execute the following commands:
   
   `docker compose -f ./logos/docker-compose.yaml build`
   
   and afterward
   
   `docker compose -f ./logos/docker-compose.yaml up`

   Inside the logs logos prints out your initial root-key to be used.

4. Access Web-UI:
   Under https://logos.ase.cit.tum.de:8080/ logos runs the Logos-UI. You can log in via your root key.

5. Important API-Endpoints
   You can access all available endpoints under https://logos.ase.cit.tum.de:8080/docs