---
title: From the Command Line
---

To run Athena, you have to start at least two processes. The assessment module manager API will be available at [http://localhost:5100](http://localhost:5100).

**Before you start the processes, make sure that you have loaded the environment variables from the** `.env` **file in each folder.** This can be achieved using

```bash
source .env
```

# The Assessment Module Manager

Start it from the `assessment_module_manager` folder using

```bash
poetry run assessment_module_manager
```

# An Assessment Module, like the `module_example`

Start it from the `module_example` (or another `module_*` folder) using

```bash
poetry run module
```
