import rospy
from sensor_msgs.msg import LaserScan, Imu
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

from modules.KalmanFilter import KalmanFilter, EKF_SLAM
from modules.ParticleFilter import ParticleFilter
import numpy as np
from numpy.random import randn
import scipy.stats

class Agent:
    def __init__(self, filter_type = 'kalman', nodeName='amr', queueSize=10):
        """
        Initiation for the bot. Setting defaults and adding Subscribers/
        Publishers. 
        """
        self.object_detected = False

        self.SetSpeed(0.5, 0, 0)
        self.current_x = None
        self.current_y = None
        self.current_z = None
        
        self.DEFAULT_SPIRAL_RADIUS = 10
        self.spiral_radius = self.DEFAULT_SPIRAL_RADIUS
        self.print_message = False
        self.filter_type = filter_type

        #self.

        if ('kalman' in filter_type):
        	self.filter = KalmanFilter()
        elif ('slam' in filter_type):
            # nObjects is True. Others I am guessing based on the environment. Should get back on it.
            # R i am really not sure about as I got it from the cited notebook.
            nObjects = 8
            initialPosition = np.array([0, -4, np.pi/2])
            self.R = np.array([[.001, .0, .0],
              [.0, .001, .0],
              [.0, .0, .0001]])

            self.filter = EKF_SLAM(initialPosition, nObjects, self.R)
        else :
        	self.filter = ParticleFilter()

        rospy.init_node(nodeName)
        
        # Subscribers
        self.laserSubscriber = rospy.Subscriber('/scan', LaserScan, self.LaserCallback)
        self.odometerySubscriber = rospy.Subscriber('odom', Odometry, self.OdometryCallback)

        # Publisher
        self.publisher = rospy.Publisher('cmd_vel', Twist, queue_size=queueSize)


        self.move = Twist()

        # Loop -- I think.
        rospy.spin()

    def SetSpeedX(self, speed):
        """Set X Speed"""
        self.x_speed = speed
    
    def SetSpeedY(self, speed):
        """Set Y Speed"""
        self.y_speed = speed
    
    def SetSpeedZ(self, speed):
        """Set Z Speed"""
        self.z_speed = speed

    def SetSpeed(self, speedX, speedY, speedZ):
        """Set X, Y and Z Speeds"""
        self.SetSpeedX(speedX)
        self.SetSpeedY(speedY)
        self.SetSpeedZ(speedZ)

    def LaserCallback(self, msg):
        """Callback for the Laser Sensor"""
        self.findDistanceBearing(msg)
        pass

    def OdometryCallback(self, msg):
        """Callback for Odometry messages"""

        self.current_x = msg.pose.pose.position.x
        self.current_y = msg.pose.pose.position.y
        self.current_z = msg.pose.pose.position.z

        if (self.filter_type == 'kalman'):

            # print (self.current_x, self.current_y, self.current_z)
            Z = np.matrix([self.current_x, self.current_y,self.current_z]).T

            self.filter.update(Z)
            filter_X = self.filter.predict()

            with open('res_measured_kalman.csv', 'a') as f:
                f.write(f'{self.current_x};{self.current_y};{self.current_z}\n')

            with open('res_predicted_kalman.csv', 'a') as f:
                f.write(f'{filter_X[0]};{filter_X[1]};{filter_X[2]}\n')
        elif (self.filter_type == 'slam'):
            # I want to get the predictions here, but I'm not too sure how this could work.
            # Working on preprocessing some of the information, but not able to figure it out yet.
            objectLocations = np.zeros((self.filter.nObjects, 3))
            objectLocations[:,0] = np.random.uniform(low=-20., high=20., size=self.filter.nObjects)
            objectLocations[:,1] = np.random.uniform(low=-20., high=20., size=self.filter.nObjects)
            objectLocations[:,2] = np.arange(self.filter.nObjects)

            

            X_hat = []
            Conv_hat = []

            dt = .1
            t = np.arange(0,40.1, dt)
            v = 1 + .5*np.cos(.4*np.pi*t)
            w = -.2 + 2*np.cos(1.2*np.pi*t)

            U = np.column_stack([v, w])
            for t, u in enumerate(U):
                Z = []

                for i in range(objectLocations.shape[0]):
                    z = np.zeros(3)
                    z[0] = np.linalg.norm([[self.current_x, self.current_y] - objectLocations[i, :2]])
                    z[1] = np.arctan2(objectLocations[i,1] - self.current_y, objectLocations[i,0] - self.current_x) - self.current_z

                    z += np.random.multivariate_normal(np.zeros(3), self.R)
                    # wrap relative bearing
                    if z[1] > np.pi:
                        z[1] = z[1] - 2*np.pi
                    if z[1] < -np.pi:
                        z[1] = z[1] + 2*np.pi
                    z[2] = objectLocations[i,2]
                    if np.abs(z[1]) < (np.pi/4)/2:
                        Z.append(z)
                
                Z = np.array(Z) 

                x_hat, cov = self.filter.filter(Z, u)
                X_hat.append(x_hat)
                Conv_hat.append(cov)
            
                with open('slam_res_x_hat_part.csv', 'a') as f:
                    f.write(f'{x_hat[0]};{x_hat[1]}\n')

                with open('slam_res_conv_part.csv', 'a') as f:
                    f.write(f'{Conv_hat}\n')

                with open('slam_res_measured_part.csv', 'a') as f:
                    f.write(f'{self.current_x};{self.current_y}\n')
            
        else :          
            self.filter.predict([self.x_speed, (self.x_speed/self.spiral_radius)])
            self.filter.update([self.current_x, self.current_y])

            # if there are not much effieicnt particles
            if(self.filter.neff() < self.filter.N/2):
                inds = self.filter.systematic_resample()
                self.filter.resample_from_index(inds)

            mu, var = self.filter.estimate()
            with open('res_pred_part.csv', 'a') as f:
                f.write(f'{mu[0]};{mu[1]}\n')

            with open('res_measured_part.csv', 'a') as f:
                f.write(f'{self.current_x};{self.current_y}\n')



    def findDistanceBearing(self, msg):
        """
        Takes callback data as input and returns the distance and
        bearing angles to the cylindrical object
        """

        ObjectDistanceBearing = {} # Key: bearing. Value: Distance at given angle.

        # we want a total of 120 degrees. I split it 60 clockwise, 60 anticlockwise
        for i in range(60): # clockwise 60
            sight = msg.ranges[i]
            if not sight == float('inf'):
                bearing = 360 - i # bearing is clockwise, angle here is anticlockwise. 
                ObjectDistanceBearing[bearing] = sight

        for i in range(300, 360): # anticlockwise 60
            sight = msg.ranges[i]
            if not sight == float('inf'):
                bearing = 360 - i # bearing is clockwise, angle here is anticlockwise.
                ObjectDistanceBearing[bearing] = sight



        # print (ObjectDistanceBearing)
        self.PrintObjectDistanceBearing(ObjectDistanceBearing)

        # [MOVE] move the bot
        self.move_spiral()

        return ObjectDistanceBearing

    def move_spiral(self):
        """
        Move the Bot in an oval kind of path.
        """
        self.move.linear.x = self.x_speed
        self.move.angular.z = self.x_speed/self.spiral_radius

        if self.spiral_radius >= 1:
            self.spiral_radius -= self.spiral_radius * 0.10
        else:
            self.spiral_radius = self.DEFAULT_SPIRAL_RADIUS * 0.85
        # print (self.spiral_radius)
        self.publisher.publish(self.move)

    def PrintObjectDistanceBearing(self, objectDistanceBearing, nearestN=10):
        if not self.print_message:
            self.print_message = True
            print (f'bearings are printed only once to the nearest {nearestN}')
            # print (f'distance is the first distance in the range\n')

        roundFunction = lambda x: nearestN * round(x/nearestN)
        printedKeys = []


        for key, value in objectDistanceBearing.items():
            roundKey = roundFunction(key)
            if not roundKey in printedKeys:
                printedKeys.append(roundKey)
                print (f'[{key}]: {value}')
                
        if len(printedKeys) > 0:
            print ('')
