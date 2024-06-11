def process_numbers(numbers):
    total = 0
    for number in numbers:
        if number % 2 == 1:
            total += number
        else:
            total -= number
    if total > 0:
        print("Positive total:", total)
    else:
        print("Non-positive total:", total)
