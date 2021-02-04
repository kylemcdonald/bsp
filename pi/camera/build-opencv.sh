CV_VERSION=4.5.1

# sudo apt update
# sudo apt-get install -y \
#     build-essential \
#     cmake \
#     gfortran \
#     libatlas-base-dev \
#     libavcodec-dev \
#     libavformat-dev \
#     libcairo2-dev \
#     libeigen3-dev \
#     libfontconfig1-dev \
#     libgdk-pixbuf2.0-dev \
#     libgtk-3-dev \
#     libhdf5-dev \
#     libjpeg-dev \
#     libpango1.0-dev \
#     libpng-dev \
#     libswscale-dev \
#     libtbb-dev \
#     libtiff5-dev \
#     libv4l-dev \
#     libx264-dev \
#     libxvidcore-dev \
#     pkg-config \
#     python3-dev \
#     python3-pyqt5 \
#     python3-pip \
#     v4l-utils
# sudo pip3 install numpy

# cd ~
# git clone --branch $CV_VERSION --depth 1 https://github.com/opencv/opencv.git

cd ~/opencv
# mkdir build
cd build
# cmake \
#     -D CMAKE_BUILD_TYPE=RELEASE \
#     -D CMAKE_INSTALL_PREFIX=/usr/local \
#     -D ENABLE_NEON=ON \
#     -D WITH_TBB=ON \
#     -D WITH_V4L=ON \
#     -D BUILD_TESTS=OFF \
#     -D INSTALL_PYTHON_EXAMPLES=OFF \
#     -D BUILD_OPENCV_PYTHON3=YES \
#     -D OPENCV_ENABLE_NONFREE=ON \
#     -D CMAKE_SHARED_LINKER_FLAGS=-latomic \
#     -D BUILD_EXAMPLES=OFF ..

# needed on raspios
# sudo sed -i 's/CONF_SWAPSIZE=100/CONF_SWAPSIZE=2048/g' /etc/dphys-swapfile
# sudo /etc/init.d/dphys-swapfile stop
# sudo /etc/init.d/dphys-swapfile start

make -j`nproc`
sudo make install

# needed on raspios
# sudo sed -i 's/CONF_SWAPSIZE=2048/CONF_SWAPSIZE=100/g' /etc/dphys-swapfile
# sudo /etc/init.d/dphys-swapfile stop
# sudo /etc/init.d/dphys-swapfile start