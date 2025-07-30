#!env python


def printProgress(p, base=0):
    total = p + base
    if total < 0:
        total = 0
    elif total > 100:
        total = 100
    print("\rProgress: {}%".format(total), end="")
