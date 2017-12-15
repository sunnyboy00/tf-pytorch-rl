# -*- coding: utf-8 -*-

import tensorflow as tf
import numpy as np
from utils.schedule import LinearSchedule
from utils.replay_buffer import ReplayBuffer
from tf_implement.dqn.dqn_net import DQN_MLP


# Actions space: Discrete
class DuelingDQN:
    def __init__(
            self,
            env,
            max_timesteps,
            n_actions,
            n_features,
            learning_rate,
            gamma,
            replace_target_iter,
            memory_size,
            batch_size,
            learning_starts,
            train_freq,
            exploration_fraction,
            exploration_final_eps,
            dueling=True,
            ckpt_dir=None):
        self.env = env
        self.max_timesteps = max_timesteps
        self.ckpt_dir = ckpt_dir
        self.n_actions = n_actions
        self.n_features = n_features
        self.lr = learning_rate
        self.gamma = gamma
        self.replace_target_iter = replace_target_iter
        self.memory_size = memory_size
        self.batch_size = batch_size
        self.learning_starts = learning_starts
        self.train_freq = train_freq
        self.exploration_fraction = exploration_fraction
        self.exploration_final_eps = exploration_final_eps
        self.dueling = dueling      # decide to use dueling DQN or not

        self.learn_step_counter = 0
        # self.memory = np.zeros((self.memory_size, n_features*2+2))
        self.replay_buffer = ReplayBuffer(self.memory_size)
        self._build_net()
        # t_params = tf.get_collection('target_net_params')
        # e_params = tf.get_collection('eval_net_params')
        t_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='target_net')
        e_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='eval_net')
        self.replace_target_op = [tf.assign(t, e) for t, e in zip(t_params, e_params)]

        self.exploration = LinearSchedule(schedule_timesteps=int(self.exploration_fraction * self.max_timesteps),
                                          initial_p=1.0,
                                          final_p=self.exploration_final_eps)
        self.sess = tf.Session()
        self.saver = tf.train.Saver()

        self.cost_his = []

    def init_variables(self):
        self.sess.run(tf.global_variables_initializer())

    def _build_net(self):

        # 评价网络
        self.s = tf.placeholder(tf.float32, [None, self.n_features], name='s')  # input
        self.q_target = tf.placeholder(tf.float32, [None, self.n_actions], name='Q_target')  # for calculating loss

        w_initializer = tf.random_normal_initializer(0., 0.3)
        b_initializer = tf.constant_initializer(0.1)

        self.q_eval = DQN_MLP(self.s, self.n_actions, w_initializer, b_initializer,
                    'eval_net', 'e', dueling=True).build()

        with tf.variable_scope('loss'):
            self.loss = tf.reduce_mean(tf.squared_difference(self.q_target, self.q_eval))
        with tf.variable_scope('train'):
            self._train_op = tf.train.RMSPropOptimizer(self.lr).minimize(self.loss)

        # 目标网络
        self.s_ = tf.placeholder(tf.float32, [None, self.n_features], name='s_')    # input

        self.q_next = DQN_MLP(self.s_, self.n_actions, w_initializer, b_initializer,
                    'target_net', 't', dueling=True, trainable=False).build()

    def choose_action(self, observation, step, eps=None):
        if eps is not None:
            eps_threshold = eps
        else:
            eps_threshold = self.exploration.value(step)
        # to have batch dimension when feed into tf placeholder
        observation = observation[np.newaxis, :]

        actions_value = self.sess.run(self.q_eval, feed_dict={self.s: observation})
        action = np.argmax(actions_value)

        if np.random.uniform() < eps_threshold:
            action = np.random.randint(0, self.n_actions)

        return action

    def learn(self):
        last_obs = self.env.reset()
        for step in range(self.max_timesteps):
            # fresh env
            self.env.render()

            # dqn choose action based on observation
            action = self.choose_action(last_obs, step)
            env_action = (action - (self.n_actions - 1) / 2) / ((self.n_actions - 1) / 4)

            # dqn take action and get next observation and reward
            obs, reward, done, info = self.env.step(np.array([env_action]))
            reward /= 10

            self.replay_buffer.add(last_obs, action, reward, obs, float(done))

            last_obs = obs

            if (step > self.learning_starts) and (step % self.train_freq == 0):
                self.learn_batch()

    def learn_batch(self):
        # weights are copied from the online network to the target network.
        if self.learn_step_counter % self.replace_target_iter == 0:
            self.sess.run(self.replace_target_op)
            print('target params replaced \n')

        obs_batch, act_batch, rew_batch, next_obs_batch, _ = self.replay_buffer.sample(self.batch_size)

        q_next = self.sess.run(self.q_next, feed_dict={self.s_: next_obs_batch})  # next observation
        q_eval = self.sess.run(self.q_eval, {self.s: obs_batch})

        q_target = q_eval.copy()

        batch_index = np.arange(self.batch_size, dtype=np.int32)
        eval_act_index = act_batch.astype(int)
        reward = rew_batch

        q_target[batch_index, eval_act_index] = reward + self.gamma * np.max(q_next, axis=1)

        _, self.cost = self.sess.run([self._train_op, self.loss],
                                     feed_dict={self.s: obs_batch,
                                                self.q_target: q_target})
        self.cost_his.append(self.cost)

        self.learn_step_counter += 1

        if self.learn_step_counter % 100 == 0:
            self.saver.save(self.sess, self.ckpt_dir + "_" + str(self.learn_step_counter))