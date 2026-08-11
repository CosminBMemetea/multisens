FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-cyclonedds-cpp \
        ros-humble-cv-bridge \
        ros-humble-message-filters \
        python3-colcon-common-extensions \
        python3-yaml \
        python3-psutil \
    && rm -rf /var/lib/apt/lists/*

# ROS_DOMAIN_ID / RMW_IMPLEMENTATION are supplied by docker-compose (from
# the repo-root .env, shared with the backend service) rather than baked in
# here - a single source of truth instead of duplicated hardcoded values.
# Running this image standalone (outside compose) needs -e flags for both.

WORKDIR /workspace
COPY src ./src

RUN . /opt/ros/humble/setup.sh && colcon build --symlink-install

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
