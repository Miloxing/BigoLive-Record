#/bin/bash

source /root/u/milo.conf
temp=${milolist[$index]}
echo "$temp"
while [ true ]; do
    if [-d "up" ]; then
        echo "$temp"
        echo "保存文件到${temp}:milo/bigo"
        folder_size=$(du -s -b up | awk '{print $1}')
        timeout=$((folder_size / 1024 / 1024 / 1024 * 400))
        # 设置超时时间的最小值
        if [ $timeout -lt 256 ]; then
            timeout=256
        fi
        echo "超时时间为${timeout}秒"
        timeout -s SIGINT $timeout rclone move up $temp:milo/bigo -P
        rclone rmdir "up"
    fi
    sleep 60
    source /root/u/milo.conf
    temp=${milolist[$index]}
done
