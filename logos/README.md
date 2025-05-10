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
Run the following command in your terminal after installation: 

```bash
poetry run uvicorn logos.main:app
```

### Docker
Change into the edutelligence-folder and run the following command:

```bash
sudo docker compose -f ./logos/docker-compose.yaml build
```

Start the service with:
```bash
sudo docker compose -f ./logos/docker-compose.yaml up -d
```

or in case an old Postgres-Database is still running:
```bash
sudo docker compose -f ./logos/docker-compose.yaml up -d --remove-orphans
```

Now all endpoints are working, and you can proceed with setting up the database.

## Configuration
Follow these steps to install and configure **Logos** as your intelligent routing and management layer for LLMs.

---

### ✅ Step 1: Initialize the Database

Start by creating the initial database schema and a root user.

- **Endpoint**: `POST /logosdb/setup`
- **What it does**:
  - Creates the necessary tables.
  - Adds a default `root` user.
  - Registers a default process.
- **Response**:  
  Returns the **Logos API Key** for the `root` user. This key is required to authenticate the following setup requests.

---

### ✅ Step 2: Add a Provider

Add a new provider, the corresponding base url, the API key and authentication syntax.
"auth_name" is the name used in the header for authorization (e.g. "api-key" for azure), 
"auth_format" is used in the header to format the authentication (e.g. "Bearer {}" for OpenAI)

- **Endpoint**: `POST /logosdb/add_provider`
- **Required Headers**:
  - `logos_key` – Your Logos API key
  - `provider_name` – Name of the provider (e.g., `OpenAI`, `Azure`)
  - `base_url` – Base URL of the provider’s API
  - `api_key` – The provider-specific API key
  - `auth_name` – Header name for authorization (e.g., `api-key`)
  - `auth_format` – Format string for the header value (e.g., `Bearer {}`)

---

### ✅ Step 3: (Optional) Add Models

This action is optional if you just want to use Logos as a proxy. Logos will then just take 
the header info of your requests and forward it to your specified provider. Otherwise, define
now what models you want to have access to over Logos. Therefore, define the model endpoint 
(without the base url) and the name of the model.

- **Endpoint**: `POST /logosdb/add_model`
- **Required Headers**:
  - `logos_key`
  - `name` – A model name (e.g., `gpt-4`)
  - `endpoint` – The relative path (without base URL)

If you're using Logos as a pure proxy, this step can be skipped.

---

### ✅ Step 4: Add Profiles

Profiles are a layer between services (called **processes**) and the LLM infrastructure.
A profile itself has a name and a process id associated with it. A process can so have many profiles. 
Each profile can then be configured to have access to certain models or providers, as explained later. 
If you don't know the ID of a process, you can find it out via the `get_process_id`-Endpoint by 
supplying a corresponding key.

- **Endpoint**: `POST /logosdb/add_profile`
- **Required Headers**:
  - `logos_key`
  - `profile_name`
  - `process_id` – The process that this profile is tied to

> 🔍 Find out the process-ID:  
> Use `GET /logosdb/get_process_id` and supply the `logos_key` in the header.

---

### ✅ Step 5: Connect Profiles with Providers

Authorize profiles to use specific providers. Therefore,
call the connect_process_provider-Endpoint with the profile ID and the corresponding `api-ID`. This `api-ID`
is obtained by calling the `get_api_id`-Endpoint for a given api-key. 

- **Endpoint**: `POST /logosdb/connect_process_provider`
- **Required Headers**:
  - `logos_key`
  - `profile_id`
  - `api_id` – Retrieved via `GET /logosdb/get_api_id` using a provider's API key

> ✅ If you're using Logos **just as a proxy**, you're done here! 🎉

---

### ➕ (Optional) Advanced Configuration

Use the steps below to enable fine-grained model routing.

---

### ✅ Step 6: Connect Profiles with Models

Allow specific profiles to access specific models.

- **Endpoint**: `POST /logosdb/connect_process_model`
- **Required Headers**:
  - `logos_key`
  - `profile_id`
  - `model_id`

---

### ✅ Step 7: Connect Models with Providers

Link models to their respective providers.

- **Endpoint**: `POST /logosdb/connect_model_provider`
- **Required Headers**:
  - `logos_key`
  - `model_id`
  - `provider_id`

---

### ✅ Step 8: Assign API Key to Models (Optional)

If a model requires its own api-key under a certain provider, you can now
connect a stored api-key to that model. Otherwise, this is not necessary. Therefore, call the 
`connect_model_api`-Endpoint as in step 7.

- **Endpoint**: `POST /logosdb/connect_model_api`
- **Required Headers**:
  - `logos_key`
  - `model_id`
  - `api_id`

---

### 🎉 Done!

You’re ready to use Logos for intelligent LLM request routing!  
Just remember to include the `logos_key` in your request header — not as data.
