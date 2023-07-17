Evaluation Data
===========================================

The Playground comes bundled with a basic set of example data to test Athena's functionalities. For more comprehensive evaluation, you can load your own data or use anonymized data from `Artemis <https://github.com/ls1intum/Artemis>`_, an open-source LMS.

Example Data
-------------------------------------------
This data is provided within the `playground/data/example` directory and is automatically utilized when launching the Playground. 

Evaluation Data
-------------------------------------------
The `playground/data/evaluation` directory is designated for your custom data used for evaluation purposes. Initially, it's left empty for you to populate. 

Artemis Evaluation Data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
If you're integrating with Artemis LMS and would like to evaluate their data, you can request an anonymized database dump from the Artemis team. This request requires a valid reason and a signed data protection agreement (NDA). For further details, please get in touch with the Artemis team.

Once the database dump is acquired, follow these steps to export the data to the Playground:

1. **Load the Database Dump:**

    .. code-block:: bash

        npm run export:artemis:1-load-anonymized-database-dump

    This command loads the data into your local MySQL database. You can use the same database as Artemis.

2. **Export the Data:**

    .. code-block:: bash

        npm run export:artemis:2-export-evaluation-data

    This exports exercises listed under `playground/scripts/artemis/evaluation_data` to the `playground/data/evaluation` directory, where you can use it for evaluation purposes.

Artemis Programming Exercises
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Artemis programming exercises are not included in the anonymized database dump. To access these exercises, you'll need to request them separately from the Artemis team. Once you have the programming exercises, an instructor from the course can export them using the following commands:

1. **Download the Repositories:**

    .. code-block:: bash

        npm run export:artemis:3-download-programming-repositories

    This command exports the programming exercises' materials and submissions to the `playground/data/evaluation` directory. The instructor should then zip these and send them to you.

2. **Link the Repositories:**

    .. code-block:: bash

        npm run export:artemis:4-link-programming-repositories

    This command links the repositories to the `exercise-*.json` files and validates if there are any missing repositories.
