#!/usr/bin/env python

import rospy
import numpy as np
# Gym
from gym import spaces
from gym.envs.registration import register
# PLEN Environment
from plen_ros.plen_env import PlenEnv
# Gazebo/ROS
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Vector3
from gazebo_msgs.msg import ContactsState
from sensor_msgs.msg import JointState
from tf.transformations import euler_from_quaternion

register(
    id='PlenWalkEnv-v0',
    entry_point='plen_ros.plen_walk:PlenWalkEnv',
    max_episode_steps=1000,  # Time Step Limit Per Episode
)


class PlenWalkEnv(PlenEnv):
    def __init__(self):
        """
        Make PLEN learn how to Walk
        """
        rospy.logdebug("Start PlenWalkEnv INIT...")

        # How long to step the simulation for (sec)
        self.running_step = 0.05

        # Agent Action Space
        low_act = np.ones(18) * -1
        high_act = np.ones(18)
        self.action_space = spaces.Box(low_act, high_act, dtype=np.float32)

        # Environment Action Space
        self.env_ranges = [
            [-1.7, 1.7],  # RIGHT LEG
            [-1.54, 0.12],
            [-1.7, 0.75],
            [-0.2, 0.95],
            [-0.95, 1.54],
            [-0.45, 0.8],
            [-1.7, 1.7],  # LEFT LEG
            [-0.12, 1.54],
            [-0.75, 1.7],
            [-0.95, 0.2],
            [-1.54, 0.95],
            [-0.8, 0.45],
            [-1.7, 1.7],  # RIGHT ARM
            [-0.15, 1.7],
            [-0.2, 0.5],
            [-1.7, 1.7],  # LEFT ARM
            [-0.15, 1.7],
            [-0.2, 0.5]
        ]

        # Possible Rewards
        self.reward_range = (-np.inf, np.inf)

        # Reward for being alive
        self.alive_reward = 2.
        # Reward for forward velocity
        self.vel_weight = 2.
        # Reward for maintaining original height
        self.init_height = 0.158
        self.height_weight = 50.
        # Reward for staying on x axis
        self.straight_weight = 10
        # Reward staying upright
        self.roll_weight = 10.
        # Reward for staying upright
        self.pitch_weight = 10.
        # Reward for minimal joint actuation
        self.joint_effort_weight = 0.035
        # Whether the episode is done due to failure
        self.dead = False

        # Observation Values

        # TODO: REPLACE SCALARS BY .YAML GET PARAM

        # JOINTS (see self.env_ranges)
        # Low values of Joint Position Space
        self.joints_low = []
        # High values of Joint Position Space
        self.joints_high = []
        for j_state in self.env_ranges:
            self.joints_low.append(j_state[0])
            self.joints_high.append(j_state[1])

        # JOINT EFFORT
        self.joint_effort_low = [-0.15] * 18
        self.joint_effort_high = [0.15] * 18

        # TORSO HEIGHT (0, 0.25)
        self.torso_height_min = 0
        self.torso_height_max = 0.25

        # TORSO TWIST (x) (-inf, inf)
        self.torso_vx_min = -np.inf
        self.torso_vx_max = np.inf

        # TORSO ROLL (-pi, pi)
        self.torso_roll_min = -np.pi
        self.torso_roll_max = np.pi

        # TORSO PITCH (-pi, pi)
        self.torso_pitch_min = -np.pi
        self.torso_pitch_max = np.pi

        # TORSO DEVIATION FROM X AXIS (-inf, inf)
        self.torso_y_min = -np.inf
        self.torso_y_max = np.inf

        # RIGHT FOOT CONTACT (0, 1)
        self.rfs_min = 0
        self.rfs_max = 1

        # LEFT FOOT CONTACT (0, 1)
        self.lfs_min = 0
        self.lfs_max = 1

        # Getting creative with filling obs space due to specific format
        obs_low = np.empty(43)
        obs_high = np.empty(43)

        for i in range(18):
            obs_low[i] = self.joints_low[i]
            obs_low[i + 18] = self.joint_effort_low[i]
            obs_high[i] = self.joints_high[i]
            obs_high[i + 18] = self.joint_effort_high[i]

        # Now fill the rest
        obs_low[36] = self.torso_height_min
        obs_high[36] = self.torso_height_max

        obs_low[37] = self.torso_vx_min
        obs_high[37] = self.torso_vx_max

        obs_low[38] = self.torso_roll_min
        obs_high[38] = self.torso_roll_max

        obs_low[39] = self.torso_pitch_min
        obs_high[39] = self.torso_pitch_max

        obs_low[40] = self.torso_y_min
        obs_high[40] = self.torso_y_max

        obs_low[41] = self.rfs_min
        obs_high[41] = self.rfs_max

        obs_low[41] = self.lfs_min
        obs_high[41] = self.lfs_max

        # obs_low = np.array([
        #     self.joints_low, self.joint_effort_low, self.torso_height_min,
        #     self.torso_vx_min, self.torso_roll_min, self.torso_pitch_min,
        #     self.torso_y_min, self.rfs_min, self.lfs_min
        # ])

        # obs_high = np.array([
        #     self.joints_high, self.joint_effort_high, self.torso_height_max,
        #     self.torso_vx_max, self.torso_roll_max, self.torso_pitch_max,
        #     self.torso_y_max, self.rfs_max, self.lfs_max
        # ])

        self.observation_space = spaces.Box(obs_low, obs_high)

        rospy.logdebug("ACTION SPACES TYPE===>" + str(self.action_space))
        rospy.logdebug("OBSERVATION SPACES TYPE===>" +
                       str(self.observation_space))

        # OBSERVATION SUBSCRIBERS

        # Odometry (Pose and Twist)
        self.torso_z = 0
        self.torso_y = 0
        self.torso_roll = 0
        self.torso_pitch = 0
        self.torso_vx = 0
        self.odom_subscriber = rospy.Subscriber('/plen/odom', Odometry,
                                                self.odom_subscriber_callback)

        # Joint Positions and Effort
        # Init
        self.joint_poses = np.zeros(18)
        self.joint_efforts = np.zeros(18)
        # Sub
        self.joint_state_subscriber = rospy.Subscriber(
            '/plen/joint_states', JointState,
            self.joint_state_subscriber_callback)

        # Right Foot Contact
        # Init
        self.right_contact = 1
        # Sub
        self.right_contact_subscriber = rospy.Subscriber(
            '/plen/right_foot_contact', ContactsState,
            self.right_contact_subscriber_callback)

        # Left Foot Contact
        self.left_contact = 1
        # Sub
        self.left_contact_subscriber = rospy.Subscriber(
            '/plen/left_foot_contact', ContactsState,
            self.left_contact_subscriber_callback)

        # Here we will add any init functions prior to starting the MyRobotEnv
        super(PlenWalkEnv, self).__init__()

        rospy.logdebug("END PlenWalkEnv INIT...")

    def odom_subscriber_callback(self, msg):
        """
            Returns cartesian position and orientation of torso middle
        """
        self.torso_z = msg.pose.pose.position.z
        self.torso_y = msg.pose.pose.position.y
        quat = [
            msg.pose.pose.orientation.x, msg.pose.pose.orientation.y,
            msg.pose.pose.orientation.z, msg.pose.pose.orientation.w
        ]
        roll, pitch, yaw = euler_from_quaternion(quat)
        self.torso_roll = roll
        self.torso_pitch = pitch
        self.torso_vx = msg.twist.twist.linear.x

    def joint_state_subscriber_callback(self, msg):
        """
            Returns joint positions and efforts

            RIGHT LEG:
            Joint 1 name: rb_servo_r_hip
            Joint 2 name: r_hip_r_thigh
            Joint 3 name: r_thigh_r_knee
            Joint 4 name: r_knee_r_shin
            Joint 5 name: r_shin_r_ankle
            Joint 6 name: r_ankle_r_foot

            LEFT LEG:
            Joint 7 name: lb_servo_l_hip
            Joint 8 name: l_hip_l_thigh
            Joint 9 name: l_thigh_l_knee
            Joint 10 name: l_knee_l_shin
            Joint 11 name: l_shin_l_ankle
            Joint 12 name: l_ankle_l_foot

            RIGHT ARM:
            Joint 13 name: torso_r_shoulder
            Joint 14 name: r_shoulder_rs_servo
            Joint 15 name: re_servo_r_elbow

            LEFT ARM:
            Joint 16 name: torso_l_shoulder
            Joint 17 name: l_shoulder_ls_servo
            Joint 18 name: le_servo_l_elbow
        """
        joint_names = [
            'rb_servo_r_hip', 'r_hip_r_thigh', 'r_thigh_r_knee',
            'r_knee_r_shin', 'r_shin_r_ankle', 'r_ankle_r_foot',
            'lb_servo_l_hip', 'l_hip_l_thigh', 'l_thigh_l_knee',
            'l_knee_l_shin', 'l_shin_l_ankle', 'l_ankle_l_foot',
            'torso_r_shoulder', 'r_shoulder_rs_servo', 're_servo_r_elbow',
            'torso_l_shoulder', 'l_shoulder_ls_servo', 'le_servo_l_elbow'
        ]

        for i in range(len(joint_names)):
            self.joint_poses[i] = msg.position[msg.name.index(joint_names[i])]
            self.joint_efforts[i] = msg.effort[msg.name.index(joint_names[i])]

    def right_contact_subscriber_callback(self, msg):
        """
            Returns whether right foot has made contact

            For a Robot of total mas of 0.495Kg, a gravity of 9.81 m/sec**2
            Weight = 0.495*9.81 = 4.8559 N

            Per Leg = Weight / 2
        """
        contact_force = Vector3()
        for state in msg.states:
            contact_force = state.total_wrench.force

        contact_force_np = np.array(
            (contact_force.x, contact_force.y, contact_force.z))

        # Contact Force Magnitude
        force_magnitude = np.linalg.norm(contact_force_np)

        if force_magnitude > 4.8559 / 2.0:
            self.right_contact = 1
        else:
            self.right_contact = 0

    def left_contact_subscriber_callback(self, msg):
        """
            Returns whether right foot has made contact

            For a Robot of total mas of 0.495Kg, a gravity of 9.81 m/sec**2
            Weight = 0.495*9.81 = 4.8559 N

            Per Leg = Weight / 2
        """
        contact_force = Vector3()
        for state in msg.states:
            contact_force = state.total_wrench.force

        contact_force_np = np.array(
            (contact_force.x, contact_force.y, contact_force.z))

        # Contact Force Magnitude
        force_magnitude = np.linalg.norm(contact_force_np)

        if force_magnitude > 4.8559 / 2.0:
            self.left_contact = 1
        else:
            self.left_contact = 0

    def env_to_agent(self, env_range, env_val):
        """ Convert an action from the Environment space
            to the Agent Space ([-1, 1])
        """
        # Convert using y = mx + b
        agent_range = [-1, 1]
        m = (agent_range[1] - agent_range[0]) / (env_range[1] - env_range[0])
        b = agent_range[1] - (m * env_range[1])
        agent_val = m * env_val + b
        return agent_val

    def agent_to_env(self, env_range, agent_val):
        """ Convert an action from the Agent space ([-1, 1])
            to the Environment Space
        """
        # Convert using y = mx + b
        agent_range = [-1, 1]
        m = (env_range[1] - env_range[0]) / (agent_range[1] - agent_range[0])
        b = env_range[1] - (m * agent_range[1])
        env_val = m * agent_val + b
        return env_val

    def _set_init_pose(self):
        """Sets the Robot in its init pose
        """
        self.joints.set_init_pose

    def _init_env_variables(self):
        """
        Inits variables needed to be initialised each time we reset at the start
        of an episode.
        :return:
        """
        # TODO

    def _set_action(self, action):
        """
        Move the robot based on the action variable given
        """
        # Pause
        self.gazebo.pauseSim()

        # Convert agent actions into real actions
        env_action = np.empty(18)
        for i in range(len(action)):
            # Convert action from [-1, 1] to real env values
            env_action[i] = self.agent_to_env(self.env_ranges[i], action[i])

        rospy.logdebug("Executing Action ==>" + str(env_action))

        # Unpause
        self.gazebo.unpauseSim()
        # Move Joints
        self.joints.move_joints(env_action)
        # Let run for running_step seconds
        # time.sleep(self.running_step)
        # Pause
        self.gazebo.pauseSim()

        rospy.logdebug("Action Completed")

    def _get_obs(self):
        """
        Here we define what sensor data of our robots observations

            - Twist
            - Torso Height
            - Torso Pitc
            - Torso Roll
            - Torso y position
            - Joint Positions
            - Joint efforts
            - Right foot contact
            - Left foot contact
        """
        observations = np.array([
            self.joint_poses, self.joint_efforts, self.torso_z, self.torso_vx,
            self.torso_roll, self.torso_pitch, self.torso_y,
            self.right_contact, self.left_contact
        ])

        observations = np.empty(43)

        for i in range(18):
            observations[i] = self.joint_poses[i]
            observations[i + 18] = self.joint_efforts[i]

        # Now fill the rest
        observations[36] = self.torso_z

        observations[37] = self.torso_vx

        observations[38] = self.torso_roll

        observations[39] = self.torso_pitch

        observations[40] = self.torso_y

        observations[41] = self.right_contact

        observations[41] = self.left_contact

        return observations

    def _is_done(self):
        """
        Decide if episode is done based on the observations

            - Pitch is above or below pi/2
            - Roll is above or below pi/2
            - Height is below height thresh
            - y position (abs) is above y thresh
            - episode timesteps above limit
        """
        if self.torso_roll > np.abs(np.pi / 3.) or self.torso_pitch > np.abs(
                np.pi / 3.) or self.torso_z < 0.07 or self.torso_y > 0.5:
            done = True
            self.dead = True
        else:
            done = False
            self.dead = False
        return done

    def _compute_reward(self, done):
        """
        Return the reward based on the observations given
        """
        reward = 0

        # Reward for being alive
        reward += self.alive_reward
        # Reward for forward velocity
        reward += np.exp(self.torso_vx) * self.vel_weight
        # Reward for maintaining original height
        reward -= (np.abs(self.init_height -
                          self.torso_z))**2 * self.height_weight
        # Reward for staying on x axis
        reward -= (np.abs(self.torso_y))**2 * self.straight_weight
        # Reward staying upright
        reward -= (np.abs(self.torso_roll))**2 * self.roll_weight
        # Reward for staying upright
        reward -= (np.abs(self.torso_pitch))**2 * self.pitch_weight
        # Reward for minimal joint actuation
        for effort in self.joint_efforts:
            reward -= effort**2 * self.joint_effort_weight
        # Whether the episode is done due to failure
        if self.dead:
            reward -= 100
        return reward