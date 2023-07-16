Playground Setup
===========================================

Playground is a web application that allows users to test Athena's functionality. Built with Next.js and React, Playground provides a user-friendly interface for debugging, evaluating Athena modules, and simulating interaction with a learning management system (LMS).

Preparation
------------------------------------------
To run Playground, make sure you have `Node.js <https://nodejs.org/en/>`_ installed on your machine. It is recommended to use the latest LTS version (>=18.14.0 < 19) 

Dependency Installation
------------------------------------------
Navigate to the `playground` directory and execute the following command to install the necessary dependencies:

.. code-block:: bash

    npm install

Running the Playground and Athena
------------------------------------------
To start the Playground, execute the following command in the `playground` directory:

.. code-block:: bash

    npm run dev

Athena must be running in order to use Playground properly. This can be achieved either by initiating the `assessment_module_manager` and a `module` locally, or by connecting to a remote Athena instance (though you have to somehow make localhost accessible to the remote instance).