import os
import sys

wait = False
keep = []
free_size = 0


def get_keep_list():
    global keep
    try:
        keep = open('./keep.txt').read().splitlines()
    except:
        keep = []
    # return keep


def get_free_size():
    global free_size
    info = os.statvfs('/')
    free_size = info.f_bsize * info.f_bavail / 1024 / 1024 / 1024  # GB
    free_size = round(free_size, 2)


def run():
    # global keep
    # global free_size
    global wait
    get_keep_list()
    get_free_size()
    if free_size <= 40 or (wait and free_size <= 45):
        sys.stdout.write(f"\r\033[KÊ£Óà¿Õ¼ä{free_size}G, Í£Ö¹ÏÂÔØ")
        wait = True
        # time.sleep(10)
    else:
        wait = False
