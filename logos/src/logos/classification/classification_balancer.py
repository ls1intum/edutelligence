"""
Module handling balancing of different weights categories.
"""


class Balancer:
    TOKEN_WEIGHT = 2
    LAURA_WEIGHT = 4

    def __init__(self):
        self.weights = {
            "policy": list(),
            "token": list(),
            "ai": list()
        }

    def __combine_policy(self):
        return sum(self.weights["policy"])

    def __combine_token(self):
        return sum(self.weights["token"])

    def __combine_ai(self):
        return sum(self.weights["ai"])

    def add_weight(self, weight: float, category: str):
        self.weights[category].append(weight)

    def get_weight(self):
        return self.__combine_policy() + self.__combine_token() * self.TOKEN_WEIGHT + self.__combine_ai() * self.LAURA_WEIGHT
