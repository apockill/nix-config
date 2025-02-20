import library_tests

def main():
    print("Validating opencv-python")
    library_tests.test_opencv()

    print("Validating torch GPU access")
    library_tests.test_torch()

    print("Validating Pillow install")
    library_tests.test_pillow()

    print("Validating genesis engine")
    library_tests.test_genesis()


if __name__ == "__main__":
    main()
