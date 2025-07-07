"""
Module handling balancing of different weights categories.
"""


class Balancer:
    def __init__(self):
        self.weights = {
            "policy": list(),
            "token": list(),
            "ai": list()
        }

    def __combine_policy(self):
        start = 0
        for i in self.weights["policy"]:
            start += i
        return start

    def __combine_token(self):
        start = 0
        for i in self.weights["token"]:
            start += i
        return start

    def __combine_ai(self):
        start = 0
        for i in self.weights["ai"]:
            start += i
        return start

    def add_weight(self, weight: float, category: str):
        self.weights[category].append(weight)

    def get_weight(self):
        return self.__combine_policy() + self.__combine_token() * 2 + self.__combine_ai() * 4
