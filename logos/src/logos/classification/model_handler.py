from typing import Union, List, Tuple


class ModelHandler:
    def __init__(self, models: List[Tuple[int, int]], base_feedback: int = 2, feedback_scale: int = 2):
        """
        Basic instance of the ModelHandler. Administrates internal model weights for one category.
        """
        self.models = models
        self.unique = self.__get_unique()
        self.base_feedback = base_feedback
        self.feedback_scale = feedback_scale

    @staticmethod
    def __rebalance(models: List[Tuple[int, int]]):
        """
        Rebalances the given model-list around the median of 0.
        """
        if not models:
            return list()
        if len(models) & 0x1:
            center = models[len(models) // 2][0]
        else:
            center = (models[len(models) // 2 - 1][0] + models[len(models) // 2][0]) // 2
        return [(i - center, j) for i, j in models]

    def add_model(self, worse_id: Union[int, None], model_id: int):
        """
        Adds a model.
        @param worse_id: ID of the best model that is worse than the model to insert or None
        @param model_id: ID of the model to insert
        """
        index = self.get_model_index(worse_id)
        if index == -1:
            # Model is the worst one so insert at the left
            index = 0
        else:
            # Insert one position after the best model that is worse than the new one
            index += 1
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Build model-tuple
        model = (self.__score(0), model_id)
        # Obtain values without feedback
        reset = self.__rebalance([(self.__score(x), j) for x, (_, j) in enumerate(self.models)])
        # Obtain user feedback
        diffs = [reset[index][0] - self.models[index][0] for index in range(len(self.models))]
        # Obtain feedback shift. This is necessary to prevent false differences after rebalancing
        feedback_shift = (self.models[0][0] + self.models[-1][0]) // 2 if len(self.models) >= 2 else 0
        # Add the model at the given position
        if index == len(self.models):
            self.models.append(model)
            diffs.append(-feedback_shift)
        else:
            self.models.insert(index, model)
            diffs.insert(index, -feedback_shift)
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Get updated models without feedback
        values = self.__rebalance([(self.__score(x), j) for x, (_, j) in enumerate(self.models)])
        # Apply feedback to the new models
        values = [(i - diffs[x], j) for x, (i, j) in enumerate(values)]
        # Rebalance for 0-median-constraint
        self.models = self.__rebalance(values)

    def remove_model(self, model_id: int):
        """
        Removes a model from the administrated list.
        @model_id: ID of the model to remove
        @raise: ValueError if the given ID is not present
        """
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Obtain values without feedback
        reset = self.__rebalance([(self.__score(x), j) for x, (_, j) in enumerate(self.models)])
        # Obtain user feedback
        diffs = [reset[index][0] - self.models[index][0] for index in range(len(self.models))]
        # Get index of element to remove
        index = self.get_model_index(model_id)
        if index == -1:
            raise ValueError("Model-ID not found")
        # Remove model
        self.models.pop(index)
        diffs.pop(index)
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Get updated models without feedback
        values = self.__rebalance([(self.__score(x), j) for x, (_, j) in enumerate(self.models)])
        # Apply feedback to the new models
        values = [(i - diffs[x], j) for x, (i, j) in enumerate(values)]
        # Rebalance for 0-median-constraint
        self.models = self.__rebalance(values)

    def give_feedback(self, model_id: int, feedback: int):
        """
        Applies feedback to a model.
        @param model_id: ID of the model to apply feedback to
        @param feedback: Feedback to apply
        """
        # Get index of element to apply feedback to
        index = self.get_model_index(model_id)
        if index == -1:
            raise ValueError("Model-ID not found")
        # Apply user feedback
        self.models[index] = self.models[index][0] + feedback, self.models[index][1]
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Obtain values without feedback
        reset = self.__rebalance([(self.__score(x), j) for x, (_, j) in enumerate(self.models)])
        # Obtain user feedback
        diffs = [reset[index][0] - self.models[index][0] for index in range(len(self.models))]
        # Reorder model list
        while index > 0 and self.models[index][0] < self.models[index - 1][0]:
            self.models[index], self.models[index - 1] = self.models[index - 1], self.models[index]
            self.models[index] = reset[index][0] - diffs[index - 1], self.models[index][1]
            index -= 1
        while index < len(self.models) - 1 and self.models[index][0] > self.models[index + 1][0]:
            self.models[index], self.models[index + 1] = self.models[index + 1], self.models[index]
            self.models[index] = reset[index][0] - diffs[index + 1], self.models[index][1]
            index += 1
        # Update number of unique weights of the models
        self.unique = self.__get_unique()
        # Rebalance for 0-median-constraint
        self.models = self.__rebalance(self.models)

    def get_model_index(self, model_id: int):
        """
        Returns the index of a model with the given ID.
        """
        found = [x for x, (_, i) in enumerate(self.models) if i == model_id]
        if not found:
            return -1
        return found[0]

    def get_models(self):
        return self.models

    def get_model_threshold(self, model_id: int):
        """
        Returns the weight assigned to a model. This is a utility function combining finding the index of a model and its weight.
        @param model_id: Model-ID
        """
        index = self.get_model_index(model_id)
        if index == -1:
            raise ValueError("Model-ID not found")
        return self.models[index][0]

    def __get_unique(self):
        """
        Returns the number of different weights assigned to models.
        """
        return len(set(i for (i, _) in self.models))

    def __score(self, position: int):
        """
        Calculates the individual score of a model depending on its position.
        """
        if self.unique == 0:
            return 0
        return self.feedback_scale * int(-self.base_feedback * self.unique + 2 * self.base_feedback * position)
