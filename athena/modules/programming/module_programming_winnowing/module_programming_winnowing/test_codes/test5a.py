def sum_first_five():
    sum = 0
    for i in range (6):
        sum += i
    return sum

def next_five(a):
    for i in range(6,11):
        a += i
    return a 

first5sum = sum_first_five()
total_sum = next_five(first5sum)
print(total_sum)
