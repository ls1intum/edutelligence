# Playground 

The Playground is a web application that allows you to test Athena's functionality. It uses Next.js as a framework and React as a library and offers a simple user interface to interact with Athena. You can mainly use the Playground to debug and evaluate your Athena modules and to test how they would interact with a learning management system (LMS).

## Setup

To run the Playground, you need to have [Node.js](https://nodejs.org/en/) installed on your machine. We recommend using the latest LTS version.

### Install dependencies

To install the dependencies, run the following command in the `playground` folder:

```bash
npm install
```

### Run the Playground and Athena

To run the Playground, run the following command in the `playground` folder:

```bash
npm run dev
```

You will need a running instance of Athena to use the Playground. You can either start the `assessment_module_manager` and some `module` locally or connect to a remote instance of Athena.

## Data

### Example Data

The Playground comes with some very basic example data that you can use to test Athena's functionality. This data is located in the `playground/data/example` folder. This data is used by default when you start the Playground.

### Evaluation Data

By default the `playground/data/evaluation` folder is empty. You can use this folder to store your own data that you want to use for evaluation purposes.

If you are working with [Artemis](https://github.com/ls1intum/Artemis) LMS and want to use their data for evaluation, you can request an anonymized copy of their database from the Artemis team. You will need to give a reason for your request and sign a data protection agreement (NDA). Please contact the Artemis team for more information.

Once you get the data, you can export it to the Playground with the following commands:

**Loading the Database Dump:**
```bash
npm run export:artemis:export:artemis:1-load-anonymized-database-dump
```

This will load the data into your local MySQL database (just reuse your Artemis database). 

**Exporting from the Database:**

Then you can export the data to the Playground with the following command:

```bash
npm run export:artemis:2-evaluation-data
```

This will export the exercises listed under `playground/scripts/artemis/evaluation` to the `playground/data/evaluation` folder. You can then use this data for evaluation purposes.

**Getting the Repositories (Programming Exercises):**

If you want to use the programming exercises, request them separately from the Artemis team: They are not included in the anonymized database dump. An instructor of the course can export the programming exercises from Artemis using the following command:

```bash
npm run export:artemis:3-materials-and-submissions
```

This will export the programming exercises' materials and submissions to the `playground/data/evaluation` folder. The instructor has to then zip it and send it to you.

**Linking the Repositories (Programming Exercises):**

In order to link the programming exercises' materials and submissions back to the exercises, you will have to run the following command:

```bash
npm run export:artemis:4-link-materials-and-submissions
```

This will link the repositories to the `exercise-*.json` files and validate if there are any missing repositories.


