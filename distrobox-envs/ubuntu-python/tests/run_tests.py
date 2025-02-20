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

    print("All tests passed! Your distrobox is ready for python development.")


if __name__ == "__main__":
    main()
