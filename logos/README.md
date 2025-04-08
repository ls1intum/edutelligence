# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resouce management, policy-based model selection, scheduling, and monitoring.

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

#### Poetry

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

### Configuration

Create the file 'logos.local.yml'. This file will contain the users
and their respective models. You can have a look into 'logos.example.yml'
as a reference. Basically, for a single user with one model
this looks like this:

```yaml
users:
  - name: "Name or Mail (unique)"
    keys:
      - model: "Model Name"
        key: "API-Key"
        pwd: "Password for this model (can be empty if private is false)"
        provider: "Where this LLM runs (default is openai)"
        quota: "How many prompts may be processed by this model (default=-1, all)"
        private: true or false, depending if this model should not be accessible 
                    without further user authentication
```

The password stored has to be hashed with bcrypt:
```py
import bcrypt
bcrypt.hashpw(password, bcrypt.gensalt())
```

If you don't want to provide a user, use the name "default". With no user provided,
logos will the automatically look under this branch.

## Running the Service

### Additional Logos API Parameters
Provide the user with the key "user" and the password with the key "password" 
in the payload of your request to access user LLMs with or without password. If you don't provide
the user, logos will look in the "default" branch of the config.

### Development

```bash
poetry run fastapi dev "./src/logos/main.py"
```

### Production

```bash
poetry run fastapi run "./src/logos/main.py"
```
