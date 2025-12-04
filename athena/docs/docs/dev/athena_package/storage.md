---
title: Storage
---

The `athena` package provides a subpackage `storage` that contains
helper functions for storing and retrieving submissions and feedback.

Each module gets its own database to store submissions and feedback. The
database is created automatically if it does not exist. Because of this,
each module can freely store anything in the `meta` field of both
submissions and feedback.

The `athena` package will automatically store all incoming submissions
and all incoming feedback from the assessment module manager in the
database. You can use the following functions from the `athena.storage`
package to further store and retrieve submissions and feedback:

- `athena.storage.store_submission`
- `athena.storage.store_submissions`
- `athena.storage.get_stored_submissions`
- `athena.storage.store_feedback`
- `athena.storage.get_stored_feedback`
- `athena.storage.store_feedback_suggestion`
- `athena.storage.get_stored_feedback_suggestions`
