FROM ros:humble-ros-base AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY src ./src

# No --symlink-install: this is a production image, not a dev workspace -
# symlink-install leaves install/ pointing back into src/, which only works
# if src/ ships in the final image too. A plain colcon build copies
# everything into install/, which is then fully self-contained and is all
# the runtime stage below needs.
RUN . /opt/ros/humble/setup.sh && colcon build

FROM ros:humble-ros-base

# colcon itself (python3-colcon-common-extensions) is a build-time-only
# dependency - not installed here, it's not needed to run `ros2 launch`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-cyclonedds-cpp \
        ros-humble-cv-bridge \
        ros-humble-message-filters \
        python3-yaml \
        python3-psutil \
    && rm -rf /var/lib/apt/lists/*

# ROS_DOMAIN_ID / RMW_IMPLEMENTATION are supplied by docker-compose (from
# the repo-root .env, shared with the backend service) rather than baked in
# here - a single source of truth instead of duplicated hardcoded values.
# Running this image standalone (outside compose) needs -e flags for both.

WORKDIR /workspace
COPY --from=build /workspace/install ./install

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
