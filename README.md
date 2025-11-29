# EduTelligence: AI-Powered Educational Technology Suite

EduTelligence is a comprehensive suite of AI-powered microservices designed to enhance Learning Management Systems (LMS) with intelligent features for education. The suite seamlessly integrates with [Artemis](https://github.com/ls1intum/Artemis) to provide automated assessment, exercise creation, competency modeling, and intelligent tutoring capabilities.

## 🔗 Artemis Compatibility

EduTelligence maintains compatibility with different versions of [Artemis](https://github.com/ls1intum/Artemis). The following table shows the compatibility matrix:

| Artemis Version | EduTelligence Version | Status    |
| --------------- | --------------------- | --------- |
| 8.0.x           | 1.0.x                 | ✅ Stable |
| 8.1.0 - 8.2.4   | 1.1.x                 | ✅ Stable |
| 8.3.0 - 8.3.4   | 1.3.x                 | ✅ Stable |
| 8.4.0 - 8.4.4   | 1.4.x                 | ✅ Stable |
| 8.5.x           | 1.5.x                 | ✅ Stable |

> **Note:** Always ensure you're using compatible versions for optimal integration and functionality.

## 🚀 Sub-Services Overview

### 🤖 [Iris](./iris/) - AI Virtual Tutor

**Pyris** - An intermediary system that connects Artemis with various Large Language Models (LLMs) to power Iris, a virtual AI tutor.

**Key Features:**

- **Exercise Support**: Provides intelligent feedback on programming exercises
- **Course Content Support**: Uses RAG (Retrieval-Augmented Generation) for detailed course content explanations
- **Competency Generation**: Automates the creation of course competencies

**Technology Stack:** Python 3.12, Poetry, FastAPI, Weaviate (Vector DB)

### ⚡ [Hyperion](./hyperion/) - AI Exercise Creation Assistant

AI-driven programming exercise creation assistance that illuminates the process of creating engaging, effective programming exercises. Designed to support instructors in refining and perfecting their educational content through intelligent analysis and enhancement.

**Key Features:**

- **Consistency Checking**: Analyzes programming exercises for conflicts between problem statements, solution code, and template code to ensure instructional coherence
- **Problem Statement Rewriting**: AI-powered improvement and refinement of exercise descriptions for enhanced clarity and pedagogical value
- **8-Step Workflow Support**: Designed to assist with the complete exercise creation process (Steps 1-7 in development)

**Technology Stack:** Python 3.13, Poetry, FastAPI, Docker

### 🏛️ [Athena](./athena/) - Automated Assessment System

A sophisticated system designed to provide (semi-)automated assessments for various types of academic exercises.

**Key Features:**

- **Multi-Exercise Support**: Text exercises, programming exercises, and planned UML/math support
- **LMS Integration**: Efficient evaluation for large courses
- **Advanced Assessment**: AI-powered grading and feedback generation

**Technology Stack:** Python, Docker Compose, PostgreSQL

**Documentation:** [https://ls1intum.github.io/edutelligence/athena/](https://ls1intum.github.io/edutelligence/athena/)

### 🗺️ [Atlas](./atlas/) - Adaptive Competency-Based Learning

A microservice that incorporates competency models into Learning Management Systems using machine learning and generative AI.

**Key Features:**

- **AI-Powered Competency Models**: Automatic generation of sophisticated competency frameworks
- **Relationship Mapping**: Automated relationships between competencies
- **Learning Activity Recommendations**: AI-driven suggestions for linking competencies to activities
- **Seamless LMS Integration**: Works with Artemis and adaptable to other LMSs

**Technology Stack:** Python, Machine Learning, GenAI/LLMs

### 📊 [Logos](./logos/) - LLM Engineering Platform

A comprehensive LLM Engineering Platform that provides centralized management and monitoring for AI services.

**Key Features:**

- **Usage Logging**: Comprehensive tracking of LLM usage
- **Billing Management**: Cost tracking and billing for AI services
- **Central Resource Management**: Unified management of AI resources
- **Policy-Based Model Selection**: Intelligent model routing based on policies
- **Scheduling & Monitoring**: Advanced scheduling and real-time monitoring

**Technology Stack:** Python 3.13, Poetry, FastAPI, Docker

[More information](https://logos.ase.cit.tum.de/)

### 🌌 [Nebula](./nebula/) - [In Development]

_Documentation and features coming soon_

**Technology Stack:** Python, Poetry

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+** (3.13 recommended for newer services)
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
