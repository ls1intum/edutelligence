# Pyris V2
Pyris is an intermediary system that links the [Artemis](https://github.com/ls1intum/Artemis) platform with various Large Language Models (LLMs). It provides a REST API that allows Artemis to interact with different pipelines based on specific tasks.

## Features
- **Modular Design**: Pyris is built to be modular, allowing for integration of new models and pipelines. This design helps the system adapt to different requirements.
- **RAG Support**: Pyris implements Retrieval-Augmented Generation (RAG) using [Weaviate](https://weaviate.io/), a vector database. This feature enables the generation of responses based on retrieved context, potentially improving the relevance of outputs.
- **Flexible Pipelines**: The system supports various pipelines that can be selected depending on the task at hand, providing versatility in handling different types of requests.

Currently, Pyris empowers [Iris](https://artemis.cit.tum.de/about-iris), a virtual AI Tutor that helps students with their programming exercises on Artemis in a didactically meaningful way.

## Setup
### With local environment
> **⚠️ Warning:** To change the local Weaviate vector database setup, please refer to [Weaviate Docs](https://weaviate.io/developers/weaviate/quickstart).

 - Check python version: `python --version` (should be 3.12)
 - Install packages: `pip install -r requirements.txt`
 - Create an `application.local.yml` file in the root directory. This file includes configurations that can be used by the application.
    - Example `application.local.yml`:
     ```yaml
    api_keys:
      - token: "secret"

    weaviate:
      host: "localhost"
      port: "8001"
      grpc_port: "50051"

    env_vars:
      test: "test"
     ```
 - Create an `llm-config.local.yml` file in the root directory. This file includes a list of models with their configurations that can be used by the application.
   - Example `llm-config.local.yml`:
     ```yaml
      - id: "<model-id>"
        name: "<custom-model-name>"
        description: "<model-description>"
        type: "<model-type>, e.g. azure-chat, ollama"
        endpoint: "<your-endpoint>"
        api_version: "<your-api-version>"
        azure_deployment: "<your-azure-deployment-name>"
        model: "<model>, e.g. gpt-3.5-turbo"
        api_key: "<your-api-key>"
        tools: []
        capabilities:
          input_cost: 0.5
          output_cost: 1.5
          gpt_version_equivalent: 3.5
          context_length: 16385
          vendor: "<your-vendor>"
          privacy_compliance: True
          self_hosted: False
          image_recognition: False
          json_mode: True
     ```
 - Each model configuration in the `llm-config.local.yml` file also include capabilities that will be used by the application to select the best model for a specific task.

#### Run server
 - Run server: 
   ```[bash]
     APPLICATION_YML_PATH=<path-to-your-application-yml-file> LLM_CONFIG_PATH=<path-to-your-llm-config-yml> uvicorn app.main:app --reload
    ```
 - Access API docs: http://localhost:8000/docs

### Getting Started with Docker

Deploying Pyris using Docker is a straightforward way to set up the application in a consistent environment. Here's how you can do it:

**Build and Run the Containers**

The essential part of setting up Pyris with Docker is building and running the containers. Docker Compose is used to manage the different services, including Pyris, Weaviate, and Nginx, for both development and production environments.

- **For Development:**

   To start the development environment, run:

   ```bash
   docker-compose -f docker-compose/pyris-dev.yml up --build
   ```

   This command will:
   - Build the Pyris application.
   - Start the Pyris application along with Weaviate in development mode.
   - Mount local configuration files for easy modification.

   The application will be available at `http://localhost:8000`.

- **For Production:**

   To start the production environment, run:

   ```bash
   docker-compose -f docker-compose/pyris-production.yml up -d
   ```

   This command will:
   - Pull the latest Pyris image from the GitHub Container Registry.
   - Start Pyris along with Weaviate and Nginx in production mode.
   - Nginx will handle SSL and serve as a reverse proxy.

   The application will be available at `https://<your-domain>`.

#### Additional Steps (Optional)

If you need to stop the containers, use:

```bash
docker-compose -f docker-compose/pyris-dev.yml down
```

or

```bash
docker-compose -f docker-compose/pyris-production.yml down
```

You can also customize the configuration for Weaviate, Pyris, and Nginx by editing their respective configuration files. However, the default setup should work fine for most users.

For development, access the API documentation at `http://localhost:8000/docs`. For production, access the application at your domain (e.g., `https://<your-domain>`).

If you need to view logs or debug, you can check the logs of specific services using:

```bash
docker-compose -f docker-compose/pyris-dev.yml logs pyris-app
```

This setup should help you run the Pyris application in both development and production environments with Docker. Ensure you modify the configuration files as per your specific requirements before deploying.
