FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive
ENV BLENDER_VERSION=4.2.21
ENV BLENDER_MAJOR=4.2
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget xz-utils \
    libxi6 libxxf86vm1 libxrender1 libxfixes3 libgl1 libgomp1 \
    libxkbcommon0 libxkbcommon-x11-0 libsm6 libxext6 libx11-6 libglu1-mesa \
    libxcursor1 libxinerama1 libxrandr2 libdbus-1-3 \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://download.blender.org/release/Blender${BLENDER_MAJOR}/blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && tar xf blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && mv blender-${BLENDER_VERSION}-linux-x64 /opt/blender \
    && ln -s /opt/blender/blender /usr/local/bin/blender \
    && rm blender-${BLENDER_VERSION}-linux-x64.tar.xz
WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt
COPY . .
CMD ["python3", "blenderWorker.py"]