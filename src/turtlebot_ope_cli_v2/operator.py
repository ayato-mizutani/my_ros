#!/usr/bin/env python
# -*- coding:utf-8 -*-

import rospy
import actionlib
from smach import State,StateMachine
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from std_msgs.msg import String, Int32
from std_srvs.srv import Empty
import json
import collections
from conferio_msgs.msg import Conferio

import roslib; roslib.load_manifest('kobuki_auto_docking')
from kobuki_msgs.msg import AutoDockingAction, AutoDockingGoal
from actionlib_msgs.msg import GoalStatus
import sys,os

NODE_NAME = "operator"

"""
ROSプログラム
ノード名operator

指定された会議室まで順序をたどりながら目標地点をTurtlebotに送信する
iPadからの入力情報をclientから受け取る
ROSのステートマシンを使用している

状態一覧
Waypoint
指定された目標座標へ移動するようにTurtlebotに目標座標を送信する
Reception
client/conf_infoのConferioの予約情報を購読待ちをし、予約情報の会議室の状態へ遷移する
WaitStartFlag
client/start_flagの購読待ちをする
MoveToRoom
指定された部屋移動を開始する状態　ここから各会議室までの座標をたどっていく
AreaScan
扉が開いているかどうか判断するarea_scannerからの情報を待つ

"""
#room_waypoints = {
#    "Room01":[["door_key_1", (-1.4, -2.7), (0.0, 0.0, 0.149230403361, 0.988802450802)],
#              ["room", ( 2.9,  0.0), (0.0, 0.0, 0.974797896522, 0.223089804646)],
#              ["door_key_2", (-1.4, -2.7), (0.0, 0.0, 0.149230403361, -0.988802450802)]],
#    "Room02":[["door_free_1", (-1.4, -2.7), (0.0, 0.0, 0.149230403361, 0.988802450802)],
#              ["room", ( 2.9,  0.0), (0.0, 0.0, 0.974797896522, 0.223089804646)],
#              ["door_free_2", (-1.4, -2.7), (0.0, 0.0, 0.149230403361, -0.988802450802)]]
#}
#initialpoint = [(-1.09, 2.48), (0.0, 0.0, -0.739811508606, 0.672814188119)]

#waypoints = [
#    ["Room01", (-1.4, -2.7), (0.0, 0.0, 0.149230403361, 0.988802450802)],
#    ["Room02", (2.9, 0.0), (0.0, 0.0, 0.974797896522, 0.223089804646)],
#    ["Room03", (-1.09, 2.48), (0.0, 0.0, -0.739811508606, 0.672814188119)]
#]

class Waypoint(State):
    def __init__(self, position, orientation):
        State.__init__(self, outcomes=['success'])

        #move_baseをクライアントとして定義
        self.client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        self.client.wait_for_server()

        #目標地点を定義
        self.goal = MoveBaseGoal()
        self.goal.target_pose.header.frame_id = 'map'
        self.goal.target_pose.pose.position.x = position[0]
        self.goal.target_pose.pose.position.y = position[1]
        self.goal.target_pose.pose.position.z = position[2]
        self.goal.target_pose.pose.orientation.x = orientation[0]
        self.goal.target_pose.pose.orientation.y = orientation[1]
        self.goal.target_pose.pose.orientation.z = orientation[2]
        self.goal.target_pose.pose.orientation.w = orientation[3]

    def execute(self, userdata):
        #目標地点を送信し結果待ち
        rospy.wait_for_service('/move_base/clear_costmaps')
        rospy.ServiceProxy('/move_base/clear_costmaps', Empty)()
        self.client.send_goal(self.goal)
        self.client.wait_for_result()
        return 'success'

#予約情報の購読待ちをし、指定された会議室への案内状態へ遷移する
class Reception(State):
    def __init__(self,room_names):
        State.__init__(self,outcomes=room_names)
        self.room_names = room_names
        self.callback_flag = 0
        self.next_goal = ''
        self.r = rospy.Rate(10)
        self.status = "reception"
        self.pub=rospy.Publisher(NODE_NAME + '/turtlebot_status', String, queue_size=10)
    def execute(self,userdata):
        #receptionについたことを配信する
        self.pub.publish(self.status)
        sub = rospy.Subscriber('client/conf_info',Conferio, self.callback)
        #client/conf_infoの購読待ちをする
        self.callback_flag = 0
        while(self.callback_flag == 0):
            self.r.sleep()
        return self.next_goal
    #client/conf_infoのコールバック関数　購読したらnext_goalに次の目標部屋をいれる
    def callback(self,msg):
        if (msg.b_RoomName in self.room_names):
            self.next_goal = msg.b_RoomName
            self.callback_flag = 1

#start_flag待ち
class WaitStartFlag(State):
    def __init__(self,status):
        State.__init__(self,outcomes=['success'])
        self.status = status
        self.callback_flag = 0
        self.r = rospy.Rate(10)
        self.pub=rospy.Publisher(NODE_NAME + '/turtlebot_status', String, queue_size=10)
    def execute(self,userdata):
        #turtlebotの到着した場所を配信
        self.pub.publish(self.status)
        sub = rospy.Subscriber('client/start_flag',String, self.callback)
        #iPadからの入力待ち
        self.callback_flag = 0
        while(self.callback_flag == 0):
            self.r.sleep()
        return 'success'
    def callback(self,msg):
        self.callback_flag = 1

#部屋まで移動
class MoveToRoom(State):
    def __init__(self):
        State.__init__(self,outcomes=['success'])
    def execute(self,userdata):
        return 'success'

#AreaScanをして扉が開いているかどうか判断する
class AreaScan(State):
    def __init__(self, room):
        State.__init__(self,outcomes=['success'])
        self.pub = rospy.Publisher(NODE_NAME + '/call_area_scan', String, queue_size = 10)
        self.callback_flag = 0
        self.r = rospy.Rate(10)
        self.room = room
    def execute(self,userdata):
        #area_scannerに会議室の場所を渡す
        self.pub.publish(self.room)
        sub = rospy.Subscriber('area_scanner/area_scan', String, self.callback)
        self.callback_flag = 0
        #area_scannerの判断待ち
        while(self.callback_flag==0):
            self.r.sleep()
        return 'success'
    def callback(self,msg):
        if(msg.data == "True"):
            self.callback_flag = 1

#充電ドックへ自動移動
class AutoDock(State):
    def __init__(self):
        State.__init__(self,outcomes=['success'])
    def execute(self,userdata):
        # add timeout setting
        client = actionlib.SimpleActionClient('dock_drive_action', AutoDockingAction)
        client.wait_for_server()

        goal = AutoDockingGoal();
        client.send_goal(goal)
        rospy.on_shutdown(client.cancel_goal)
        client.wait_for_result()
        return 'success'


class Operator:
    def __init__(self, r_w_j_p):
        rospy.init_node(NODE_NAME)
        #目標地点リスト　名前, 座標, 向き jsonファイルで読み込み
        decoder = json.JSONDecoder(object_pairs_hook=collections.OrderedDict)
        room_waypoints_jsonfile_path = r_w_j_p
        with open(room_waypoints_jsonfile_path) as f:
            df = decoder.decode(f.read())
        #初期位置
        initial_point = df["initial_point"]
        #目標地点リスト
        room_waypoints = df["room_waypoints"]
        #waypointsから目標地点名のみ抽出
        room_names = []
        for w in room_waypoints:
            room_names.append(w)
        #ステートマシンの状態にreception,move_to_recepotion,roomnameなどを追加
        self.operator = StateMachine(['success','reception','auto_dock','move_to_reception'] + room_names)
        #reception状態の遷移先を定義(各会議室)
        reception_transitions={}
        for r in room_names:
            reception_transitions[r] = r


        with self.operator:
            #受けつけ、受付まで移動状態を追加
            StateMachine.add('move_to_reception',
                             Waypoint(initial_point["position"],
                                      initial_point["orientation"]),
                             transitions={'success':'reception'})
            StateMachine.add('auto_dock',AutoDock(),
                             transitions={'success':'reception'})
            StateMachine.add('reception',Reception(room_names),
                             transitions=reception_transitions)

            #会議室までの道のりを座標名ごとに座標や状態を登録
            for r in room_names:
                waypoints = room_waypoints[r]
                next_move_state_names = []# [Navigate_Room01_door_key_1, Room01_room]
                next_wait_state_names = []# [Navigate_Room01_door_key_1_wait, Room01_room_wait]
                for w_n in waypoints:
                        next_move_state_names.append('Navigate_'+r+'_'+w_n)#Navigate_
                        next_wait_state_names.append('Navigate_'+r+'_'+w_n+'_wait')#Navigate_
                        rospy.loginfo('Navigate_'+r+'_'+w_n)#Navigate_
                self.operator.register_outcomes(next_move_state_names+next_wait_state_names)
                next_move_state_names.append('move_to_reception')

                StateMachine.add(r,MoveToRoom(),transitions={'success':next_move_state_names[0]})
                for i, (w_n,w) in enumerate(waypoints.items()):
                    w_n_split = w_n.split("_")
                    if(w_n_split[0] == "room"):
                        StateMachine.add(next_move_state_names[i],
                                         Waypoint(w["position"],
                                                  w["orientation"]),
                                         transitions={'success':next_wait_state_names[i]})
                        StateMachine.add(next_wait_state_names[i],
                                         WaitStartFlag(next_move_state_names[i]),
                                         transitions={'success':next_move_state_names[i+1]})
                    elif(w_n_split[0] == "door"):
                        if(w_n_split[1] == "areascan"):
                            areascan_state_scan_name = next_move_state_names[i] + "_scan"
                            areascan_state_move_name = next_move_state_names[i] + "_move"
                            self.operator.register_outcomes([areascan_state_scan_name,
                                                        areascan_state_move_name])
                            StateMachine.add(next_move_state_names[i],
                                             Waypoint(w[0]["position"],
                                                      w[0]["orientation"]),
                                             transitions={'success':next_wait_state_names[i]})
                            StateMachine.add(next_wait_state_names[i],
                                             WaitStartFlag(next_move_state_names[i]),
                                             transitions={'success':areascan_state_move_name})
                            StateMachine.add(areascan_state_move_name,
                                             Waypoint(w[1]["position"],
                                                      w[1]["orientation"]),
                                             transitions={'success':areascan_state_scan_name})
                            StateMachine.add(areascan_state_scan_name,
                                             AreaScan(r),
                                             transitions={'success':next_move_state_names[i+1]})
                        else:
                            StateMachine.add(next_move_state_names[i],
                                             Waypoint(w[0]["position"],
                                                      w[0]["orientation"]),
                                             transitions={'success':next_wait_state_names[i]})
                            StateMachine.add(next_wait_state_names[i],
                                             WaitStartFlag(next_move_state_names[i]),
                                             transitions={'success':next_move_state_names[i+1]})
    def run(self):
        self.operator.execute()
        return

if __name__ == '__main__':
    room_waypoints_jsonfile_path_list = ["/home/a-mizutani/catkin_ws/src/icclab_turtlebot/maps/modified_lobby_waypoints.json", 
                                         "/home/turtlebot/catkin_ws/src/icclab_turtlebot/maps/modified_lobby_waypoints.json"]
    try:
        room_waypoints_jsonfile_path = rospy.get_param("/operator/jsonfile_path", 'NoParam')
        if room_waypoints_jsonfile_path == 'NoParam':
            for fp in room_waypoints_jsonfile_path_list:
                if os.path.isfile(fp):
                    print("notarg "+room_waypoints_jsonfile_path)
                    room_waypoints_jsonfile_path = fp
                    break
        a = Operator(room_waypoints_jsonfile_path)
        a.run()
    except:
        rospy.loginfo("No such json file")



