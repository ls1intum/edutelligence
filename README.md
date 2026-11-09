# EduTelligence: AI-Powered Educational Technology Suite

EduTelligence is a comprehensive suite of AI-powered microservices designed to enhance Learning Management Systems (LMS) with intelligent features for education. The suite seamlessly integrates with [Artemis](https://github.com/ls1intum/Artemis) to provide automated assessment, exercise creation, competency modeling, and intelligent tutoring capabilities.

## 🔗 Artemis Compatibility

EduTelligence maintains compatibility with different versions of [Artemis](https://github.com/ls1intum/Artemis). The following table shows the current release line, newest first:

| Artemis Version | EduTelligence Version | Status    |
| --------------- | --------------------- | --------- |
| 10.6.x          | 3.6.x                 | ✅ Stable |
| 10.5.x          | 3.5.x                 | ✅ Stable |
| 10.4.x          | 3.4.x                 | ✅ Stable |
| 10.3.x          | 3.3.x                 | ✅ Stable |
| 10.2.x          | 3.2.x                 | ✅ Stable |
| 10.1.x          | 3.1.x                 | ✅ Stable |
| 10.0.x          | 3.0.x                 | ✅ Stable |

For older versions (Artemis 9.x and 8.x), see the [full compatibility matrix](https://ls1intum.github.io/edutelligence/iris/docs/overview/compatibility/) in the documentation.

> **Note:** Always ensure you're using compatible versions for optimal integration and functionality.

## Pipeline and lifecycle references

- **Iris:** [Pipeline system](https://ls1intum.github.io/edutelligence/iris/docs/developer/pipeline-system) and [RAG pipeline](https://ls1intum.github.io/edutelligence/iris/docs/developer/rag-pipeline)
- **Athena:** [Module request lifecycle](https://ls1intum.github.io/edutelligence/athena/docs/dev/module/request-lifecycle)

## 🚀 Sub-Services Overview

### 🤖 [Iris](./iris/) - AI Virtual Tutor

**Pyris** - An intermediary system that connects Artemis with various Large Language Models (LLMs) to power Iris, a virtual AI tutor.

**Key Features:**

- **Exercise Support**: Provides intelligent feedback on programming exercises
- **Course Content Support**: Uses RAG (Retrieval-Augmented Generation) for detailed course content explanations
- **Competency Generation**: Automates the creation of course competencies

**Technology Stack:** Python 3.13, Poetry, FastAPI, Weaviate (Vector DB)

### 🏛️ [Athena](./athena/) - Automated Assessment System

A sophisticated system designed to provide (semi-)automated assessments for various types of academic exercises.

**Key Features:**

- **Multi-Exercise Support**: Text exercises, programming exercises, and planned UML/math support
- **LMS Integration**: Efficient evaluation for large courses
- **Advanced Assessment**: AI-powered grading and feedback generation

**Technology Stack:** Python, Docker Compose, PostgreSQL

**Documentation:** [https://ls1intum.github.io/edutelligence/athena/](https://ls1intum.github.io/edutelligence/athena/)

### AtlasML

AtlasML is being retired; its source and history are available in the [archive](https://github.com/ls1intum/atlas-ml-archive).

## 🚀 Quick Start

### Prerequisites

- **Python 3.13** for Iris; **Python 3.11** for Athena
- **Poetry** for dependency management
- **Docker & Docker Compose** for containerization
- **Git** for version control

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/ls1intum/edutelligence.git
   cd edutelligence
   ```

2. **Choose your service(s):**
   Navigate to the specific service directory you want to set up and follow its individual README instructions.

### Development Setup

Each service has its own development setup instructions in its respective README file. Generally, the process involves:

1. Installing Poetry dependencies
2. Setting up configuration files
3. Running the service locally or via Docker

## 🤝 Contributing

We welcome contributions to improve EduTelligence! Please follow these guidelines:

1. **Fork the repository** and create a feature branch
2. **Follow the coding standards** defined in each service's documentation
3. **Write tests** for new functionality
4. **Update documentation** as needed
5. **Submit a pull request** with a clear description of changes

### Code Quality

- All services use **pre-commit hooks** for code quality
- **Linting** with flake8/pylint
- **Formatting** with black
- **Type checking** where applicable

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/ls1intum/edutelligence/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ls1intum/edutelligence/discussions)
- **Documentation**: Individual service READMEs and documentation
