from itertools import count
from collections import namedtuple
from sys import stdout

import argparse
import numpy as np
import gym

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.autograd as autograd
from torch.autograd import Variable


def from_gym(x):
    t = torch.from_numpy(x).transpose(0, 2)
    v = Variable(t).cuda()
    return v.unsqueeze(0).float()

def print_action(act_num):
    if act_num == 0:
        print('.', end='')
    elif act_num == 1:
        print('F', end='')
    elif act_num == 2:
        print('>', end='')
    elif act_num == 3:
        print('<', end='')
    stdout.flush()

SavedAction = namedtuple('SavedAction', 'action, value')

class Policy(nn.Module):
    def __init__(self, action_space):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 8, kernel_size=2, stride=2)
        self.conv2 = nn.Conv2d(8, 16, kernel_size=3, stride=2, dilation=2)
        self.conv3 = nn.Conv2d(16, 32, kernel_size=4, stride=2)
        self.conv4 = nn.Conv2d(32, 64, kernel_size=5, stride=2, dilation=2)
        self.conv5 = nn.Conv2d(64, 128, kernel_size=5, stride=2)
        self.common_affine = nn.Linear(256, 256)
        self.action_head = nn.Linear(256, action_space)
        self.value_head = nn.Linear(256, 1)

        self.saved_actions = []
        self.rewards = []

    def forward(self, x):
        h1 = F.relu(self.conv1(x))
        h2 = F.relu(self.conv2(h1))
        h3 = F.relu(self.conv3(h2))
        h4 = F.relu(self.conv4(h3))
        h5 = F.relu(self.conv5(h4)).view(-1, 256)
        h6 = F.relu(self.common_affine(h5))
        action_scores = F.softmax(self.action_head(h6))
        state_values = self.value_head(h6)
        return action_scores, state_values

    def select_action(self, state):
        probs, state_value = self(from_gym(state))
        action = probs.multinomial()
        self.saved_actions.append(SavedAction(action, state_value))
        a = probs.data[0]
        print('Chosen: {act} | NOOP: {a[0]:.02}\tFIRE: {a[1]:.02}\tRIGHT: {a[2]:.02}\tLEFT: {a[3]:.02}'.format(a=a, act=action.data[0,0]))
        return action.data


def main():
    args = parse_arguments()
    torch.manual_seed(args.seed)

    runner = Runner(args, 'Breakout-v4')
    runner.run()

class Runner:
    def __init__(self, args, env_name):
        self.env = gym.make(env_name)
        self.model = Policy(self.env.action_space.n).cuda()
        self.optimizer = optim.Adam(self.model.parameters(), lr=3e-2)

        self.gamma = args.gamma
        self.render = args.render
        self.log_interval = args.log_interval

        self.running_reward = 10

    def run(self):
        for i_episode in count(1):
            state = self.env.reset()
            for t in range(1000):
                action = self.model.select_action(state)
                state, reward, done, _ = self.env.step(action[0, 0])
                print_action(action[0, 0])
                if self.render:
                    self.env.render()
                self.model.rewards.append(reward)
                if done:
                    break
            self.running_reward = (self.running_reward * self.gamma) + \
                                  t * (1.0 - self.gamma)
            self.finish_episode(i_episode)

    def finish_episode(self, ep):
        print('Episode', ep, 'finished')
        R = 0
        saved_actions = self.model.saved_actions
        value_loss = 0
        rewards = []
        for r in self.model.rewards[::-1]:
            R = r + self.gamma * R
            rewards.insert(0, R)
        rewards = torch.Tensor(rewards)
        rewards = (rewards - rewards.mean()) / \
                  (rewards.std() + np.finfo(np.float32).eps)
        for (action, value), r in zip(saved_actions, rewards):
            reward = r - value.data[0, 0]
            action.reinforce(reward)
            value_loss += F.smooth_l1_loss(value, Variable(torch.Tensor([r])).cuda())
        self.optimizer.zero_grad()
        final_nodes = [value_loss] + list(map(lambda p: p.action, saved_actions))
        gradients = [torch.ones(1).cuda()] + [None] * len(saved_actions)
        autograd.backward(final_nodes, gradients)
        self.optimizer.step()
        del self.model.rewards[:]
        del self.model.saved_actions[:]


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Do some reinforcement learning')
    parser.add_argument('--seed', type=int, default=1,
                        metavar='SEED')
    parser.add_argument('--render', action='store_true',
                        help="Whether to render the game")
    parser.add_argument('--log-interval', type=int, default=100,
                        metavar='N', help="Interval between status logs")
    parser.add_argument('--gamma', type=float, default=0.99, metavar='G',
                        help='Decay rate for rewards')
    return parser.parse_args()

if __name__ == '__main__':
    main()