# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.7
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# ## Database Setup
# This notebook contains the necessary steps to set up the MySQL database from the provided dump file.

# %% [markdown]
# ### Setting Variables
# The first step is to set the necessary variables.
# These variables include the MySQL container name, database name, user, password, host, port, and the path to the dump file.
# Set these variables in the `.env` file (You can copy the `.env.example` file and rename it to `.env`).
# Make sure to update the `DUMP_FILE_PATH`.

# %%
import os
from dotenv import load_dotenv

DUMP_FILE_PATH = "../data/artemis_database_dump_anonymized_2023_03_29.sql"

load_dotenv()
MYSQL_CONTAINER_NAME = os.getenv("DB_CONTAINER_NAME")
MYSQL_DATABASE = os.getenv("DB_NAME")
MYSQL_USER = os.getenv("DB_USER")
MYSQL_PASSWORD = os.getenv("DB_PASSWORD")
MYSQL_HOST = os.getenv("DB_HOST")
MYSQL_PORT = os.getenv("DB_PORT")

# %% [markdown]
# ### Database Container Initialization
# Initialize the MySQL database container. Wait for the container to be up and running before proceeding to the next step.

# %%
import subprocess

command = ["docker", "run", "--name", MYSQL_CONTAINER_NAME]
command.extend(["-e", f"MYSQL_ROOT_PASSWORD={MYSQL_PASSWORD}"] if MYSQL_PASSWORD else ["-e", "MYSQL_ALLOW_EMPTY_PASSWORD=yes"])
command.extend(["-p", f"{MYSQL_PORT}:3306", "-d", "mysql:8.0"])

subprocess.run(command, check=True)


# %% [markdown]
# ### Database Configuration
# The next step is to configure the MySQL database.
# This configuration includes creating the database and setting the necessary global variables.
# Not setting the global variables may result in errors during the restoration process due to the large size of the dump file.

# %%
config_command = (
    f"docker exec -i {MYSQL_CONTAINER_NAME} mysql -u{MYSQL_USER} -e "
    f"\"CREATE DATABASE IF NOT EXISTS {MYSQL_DATABASE} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\" "
    f"-e \"SET GLOBAL net_buffer_length=1000000;\" "
    f"-e \"SET GLOBAL max_allowed_packet=1000000000;\" "
)
success_status = os.system(config_command)

print("Database configuration complete!" if success_status == 0 else "Database configuration failed!")

# %% [markdown]
# ### Database Restoration
# The next step is to restore the database from the provided dump file.
# This process may take a few minutes to complete.
# On a M1 Max MacBook, the restoration process took approximately 18 minutes.

# %%
restore_command = (
    f"docker exec -i {MYSQL_CONTAINER_NAME} mysql -u{MYSQL_USER} {MYSQL_DATABASE} < {DUMP_FILE_PATH}"
)
success_status = os.system(restore_command)

print("Database restoration complete!" if success_status == 0 else "Database restoration failed!")

