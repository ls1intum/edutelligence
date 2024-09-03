# Pyris V2
Pyris is an intermediary system that links the [Artemis](https://github.com/ls1intum/Artemis) platform with various Large Language Models (LLMs). It provides a REST API that allows Artemis to interact with different pipelines based on specific tasks.

## Features
- **Modular Design**: Pyris is built to be modular, allowing for integration of new models and pipelines. This design helps the system adapt to different requirements.
- **RAG Support**: Pyris implements Retrieval-Augmented Generation (RAG) using [Weaviate](https://weaviate.io/), a vector database. This feature enables the generation of responses based on retrieved context, potentially improving the relevance of outputs.
- **Flexible Pipelines**: The system supports various pipelines that can be selected depending on the task at hand, providing versatility in handling different types of requests.

Currently, Pyris empowers [Iris](https://artemis.cit.tum.de/about-iris), a virtual AI Tutor that helps students with their programming exercises on Artemis in a didactically meaningful way.

## Setup
### With local environment
> **⚠️ Warning:** For local Weaviate vector database setup, please refer to [Weaviate Docs](https://weaviate.io/developers/weaviate/quickstart).
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

### With docker
Pyris can be deployed using Docker, which provides an easy way to set up the application in a consistent environment.
Below are the instructions for setting up Pyris using Docker.

#### Prerequisites
- Ensure Docker and Docker Compose are installed on your machine.
- Clone the Pyris repository to your local machine.
- 
#### Setup Instructions

1. **Build and Run the Containers**

   You can run Pyris in different environments: development or production. Docker Compose is used to orchestrate the different services, including Pyris, Weaviate, and Nginx.

   - **For Development:**

     Use the following command to start the development environment:

     ```bash
     docker-compose -f docker-compose/pyris-dev.yml up --build
     ```

     This command will:
     - Build the Pyris application from the Dockerfile.
     - Start the Pyris application along with Weaviate in development mode.
     - Mount the local configuration files (`application.local.yml` and `llm-config.local.yml`) for easy modification.

     The application will be available at `http://localhost:8000`.

   - **For Production:**

     Use the following command to start the production environment:

     ```bash
     docker-compose -f docker-compose/pyris-production.yml up -d
     ```

     This command will:
     - Pull the latest Pyris image from the GitHub Container Registry.
     - Start the Pyris application along with Weaviate and Nginx in production mode.
     - Nginx will serve as a reverse proxy, handling SSL termination if certificates are provided.

     The application will be available at `https://<your-domain>`.

2. **Configuration**

   - **Weaviate**: Weaviate is configured via the `weaviate.yml` file. By default, it runs on port 8001.
   - **Pyris Application**: The Pyris application configuration is handled through environment variables and mounted YAML configuration files.
   - **Nginx**: Nginx is used for handling requests in a production environment and is configured via `nginx.yml`.

3. **Accessing the Application**

   - For development, access the API documentation at: `http://localhost:8000/docs`
   - For production, access the application at your domain (e.g., `https://<your-domain>`).

4. **Stopping the Containers**

   To stop the running containers, use:

   ```bash
   docker-compose -f docker-compose/pyris-dev.yml down
   ```

   or

   ```bash
   docker-compose -f docker-compose/pyris-production.yml down
   ```

5. **Logs and Debugging**

   - View the logs for a specific service, e.g., Pyris:

     ```bash
     docker-compose -f docker-compose/pyris-dev.yml logs pyris-app
     ```

   - For production, ensure that Nginx and Weaviate services are running smoothly and check their respective logs if needed.

---

This setup should help you run the Pyris application in both development and production environments with Docker. Ensure you modify the configuration files as per your specific requirements before deploying.