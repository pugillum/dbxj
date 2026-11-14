import random


def main():
    # if random number is odd, raise an exception
    if random.randint(0, 10) % 2 == 1:
        raise Exception("Random number is odd!")


if __name__ == "__main__":
    main()
