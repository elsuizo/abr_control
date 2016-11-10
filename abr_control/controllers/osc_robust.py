import numpy as np


class controller:
    """ Implements an operational space controller (OSC)
    """

    def __init__(self, robot_config, kp=100, kv=None, vmax=0.5):

        self.robot_config = robot_config

        # proportional gain term
        self.kp = kp
        # derivative gain term
        self.kv = np.sqrt(self.kp) if kv is None else kv
        # velocity limit of the end-effector
        self.vmax = vmax

    def control(self, q, dq, target_state):
        """ Generates the control signal

        q np.array: the current joint angles
        dq np.array: the current joint velocities
        target_state np.array: the target [pos, vel] for the end-effector
        """

        # calculate position of the end-effector
        xyz = self.robot_config.T('EE', q)

        # calculate the Jacobian for the end effector
        JEE = self.robot_config.J('EE', q)

        # calculate the inertia matrix in joint space
        Mq = self.robot_config.Mq(q)

        # calculate the effect of gravity in joint space
        Mq_g = self.robot_config.Mq_g(q)

        # convert the mass compensation into end effector space
        Mx_inv = np.dot(JEE, np.dot(np.linalg.pinv(Mq), JEE.T))
        svd_u, svd_s, svd_v = np.linalg.svd(Mx_inv)
        # cut off any singular values that could cause control problems
        singularity_thresh = .00025
        for ii in range(len(svd_s)):
            svd_s[ii] = 0 if svd_s[ii] < singularity_thresh else \
                1./float(svd_s[ii])
        # numpy returns U,S,V.T, so have to transpose both here
        Mx = np.dot(svd_v.T, np.dot(np.diag(svd_s), svd_u.T))

        # calculate desired force in (x,y,z) space
        dx = np.dot(JEE, dq)
        # implement velocity limiting
        lamb = self.kp / self.kv
        x_tilde = xyz - target_state[:3]
        sat = self.vmax / (lamb * np.abs(x_tilde))
        scale = np.ones(3)
        if np.any(sat < 1):
            index = np.argmin(sat)
            unclipped = self.kp * x_tilde[index]
            clipped = self.kv * self.vmax * np.sign(x_tilde[index])
            scale = np.ones(3) * clipped / unclipped
            scale[index] = 1
        u_xyz = -self.kv * (dx - target_state[3:] -
                            np.clip(sat / scale, 0, 1) *
                            -lamb * scale * x_tilde)
        # u_xyz = -self.kv * (dx - target_state[3:] -
        #                     np.clip(self.vmax / (lamb * np.abs(x_tilde)),
        #                             0, 1) * -lamb * x_tilde)
        # u_xyz = -self.kp * x_tilde - self.kv * dx
        u_xyz = np.dot(Mx, u_xyz)

        self.training_signal = np.dot(JEE.T, u_xyz)
        # add in gravity compensation, not included in training signal
        u = self.training_signal - Mq_g

        # calculate the null space filter
        Jdyn_inv = np.dot(Mx, np.dot(JEE, np.linalg.inv(Mq)))
        null_filter = (np.eye(self.robot_config.num_joints) -
                       np.dot(JEE.T, Jdyn_inv))

        q_des = np.zeros(self.robot_config.num_joints)
        dq_des = np.zeros(self.robot_config.num_joints)

        # calculated desired joint angle acceleration using rest angles
        for ii in range(1, self.robot_config.num_joints):
            if self.robot_config.rest_angles[ii] is not None:
                q_des[ii] = (
                    ((self.robot_config.rest_angles[ii] - q[ii]) + np.pi) %
                     (np.pi*2) - np.pi)
                dq_des[ii] = dq[ii]
        # only compensate for velocity for joints with a control signal
        nkp = self.kp * .1
        nkv = np.sqrt(nkp)
        u_null = np.dot(Mq, (nkp * q_des - nkv * dq_des))

        u += np.dot(null_filter, u_null)

        return u