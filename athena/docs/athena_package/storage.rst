Storage
===========================================

The ``athena`` package provides a subpackage ``storage`` that contains helper functions for storing and retrieving submissions and feedback.

Each module gets its own database to store submissions and feedback. The database is created automatically if it does not exist. Because of this, each module can freely store anything in the ``meta`` field of both submissions and feedback.

The ``athena`` package will automatically store all incoming submissions and all incoming feedback from the assessment module manager in the database. You can use the following functions from the ``athena.storage`` package to further store and retrieve submissions and feedback:

.. autofunction:: athena.storage.store_submission
.. autofunction:: athena.storage.store_submissions
.. autofunction:: athena.storage.get_stored_submissions
.. autofunction:: athena.storage.store_feedback
.. autofunction:: athena.storage.get_stored_feedback
.. autofunction:: athena.storage.store_feedback_suggestions
.. autofunction:: athena.storage.get_stored_feedback_suggestions