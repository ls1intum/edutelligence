def process_numbers(numbers):
    total = 1
    for number in numbers:
        if number % 2 == 0:
            total += number
        else:
            total -= number
    if total > 0:
        print("Positive total:", total)
    else:
        print("Non-positive total:", total)
