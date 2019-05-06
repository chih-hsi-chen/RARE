#!/usr/bin/env python2
# -*- coding: utf-8 -*-
import argparse, grpc, os, sys
from time import sleep

# set our lib path
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
        '../../utils/'))
# And then we import
import p4runtime_lib.bmv2
from p4runtime_lib.switch import ShutdownAllSwitchConnections
import p4runtime_lib.helper

dry_run = False;

def setDefaultDrop(p4info_helper,ingress_sw):
    """
        Default drop
    """
    table_entry_ipv4 = p4info_helper.buildTableEntry(
        table_name="Basic_ingress.ipv4_lpm",
        default_action=True,
        action_name="Basic_ingress.drop",
        action_params={})
    table_entry_mpls = p4info_helper.buildTableEntry(
        table_name="Basic_ingress.mpls_exact",
        default_action=True,
        action_name="Basic_ingress.drop",
        action_params={})
    ingress_sw.WriteTableEntry(table_entry_ipv4, dry_run)
    ingress_sw.WriteTableEntry(table_entry_mpls, dry_run)
    print "Installed Default Drop Rule on %s" % ingress_sw.name

def writeForwardRules(p4info_helper,ingress_sw,
    dst_eth_addr,port,dst_ip_addr):
    """
        Install rules:

        sx-runtime.json
            p4info_helper:  the P4Info helper
            ingress_sw:     the ingress switch connection
            dst_eth_addr:   the destination IP to match in the ingress rule
            port:           port of switch
            dst_ip_addr:    the destination Ethernet address to write in the egress rule
    """

    # 1. Ingress rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="Basic_ingress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr,32)
        },
        action_name="Basic_ingress.ipv4_forward",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": port
        })
    # write into ingress of target sw
    ingress_sw.WriteTableEntry(table_entry, dry_run)
    print "Installed MPLS-ingress rule on %s" % ingress_sw.name

def writeMplsIngressRules(p4info_helper,ingress_sw,
    dst_ip_addr,port,label):
    """
        Install rules:

        sx-runtime.json
            p4info_helper:  the P4Info helper
            ingress_sw:     the ingress switch connection
            dst_ip_addr:    target IP addr
            port:           port of switch
            label:          MPLS label
    """

    # 1. Ingress rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="Basic_ingress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr,32)
        },
        action_name="Basic_ingress.mpls_ingress",
        action_params={
            "port": port,
            "new_label": label
        })
    # write into ingress of target sw
    ingress_sw.WriteTableEntry(table_entry, dry_run)
    print "Installed MPLS-ingress rule on %s" % ingress_sw.name

def writeMplsCoreRules(p4info_helper, ingress_sw,
    port, dst_label, new_label):
    """
        Core LSR(Label Switch Router) in MPLS
    """

    # Using "exact" mode
    table_entry = p4info_helper.buildTableEntry(
        table_name="Basic_ingress.mpls_exact",
        match_fields={
            "hdr.mpls.label": (dst_label)
        },
        action_name="Basic_ingress.mpls_core",
        action_params={
            "port": port,
            "new_label": new_label
        }
    )
    # write into ingress
    ingress_sw.WriteTableEntry(table_entry,dry_run)
    print "Installed MPLS-core rule on %s" % ingress_sw.name

def writeMplsEgressRules(p4info_helper, ingress_sw,
    dst_eth_addr, port, dst_label):
    """
        Egress LSR in MPLS
    """
    table_entry=p4info_helper.buildTableEntry(
        table_name="Basic_ingress.mpls_exact",
        match_fields={
            "hdr.mpls.label": (dst_label)
        },
        action_name="Basic_ingress.mpls_egress",
        action_params={
            "dstAddr": dst_eth_addr,
            "port": port
        }
    )

    # write into ingress
    ingress_sw.WriteTableEntry(table_entry,dry_run)
    print "Installed MPLS-egress rule on %s" % ingress_sw.name

def readTableRules(p4info_helper, sw):
    """
        Reads the table entries from all tables on the switch.
        Args:
            p4info_helper:  the P4Info helper
            sw:             the switch connection
    """
    print '\n----- Reading table rules for %s ------' % sw.name
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            # TOOD:
            # use the p4info_helper to translate the IDs in the entry to names
            table_name = p4info_helper.get_tables_name(entry.table_id)
            print '%s: ' % table_name,
            for m in entry.match:
                print p4info_helper.get_match_field_name(table_name, m.field_id)
                print '%r' % (p4info_helper.get_match_field_value(m),),
            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)
            print '->', action_name,
            for p in action.params:
                print p4info_helper.get_action_param_name(action_name, p.param_id),
                print '%r' % p.value
            print

def printCounter(p4info_helper, sw, counter_name, index):
    """
        print counter_name from sw at index
        index ~ tunnel-id 
        if index=0，return all counter values
        Args:
            p4info_helper:  the P4Info Helper
            sw:             the switch connection
            counter_name:   the name of the counter from the P4 program
            index:          the counter index (in our case, the Tunnel ID)
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print "[SW: %s][Cnt: %s][Port: %d]: %d packets (%d bytes)" % (sw.name,counter_name, index,counter.data.packet_count, counter.data.byte_count)

def printGrpcError(e):
    print "gRPC Error: ", e.details(),
    status_code = e.code()
    print "(%s)" % status_code.name,
    # detail about sys.exc_info - https://docs.python.org/2/library/sys.html#sys.exc_info
    traceback = sys.exc_info()[2]
    print "[%s:%s]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno)

def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    # - then need to read from the file compiled from P4 Program, which call .p4info
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        """
            P4Runtime gRPC
            dump P4Runtime proto files in logs
            P4 port # start 50051
         """
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')
        s2 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s2',
            address='127.0.0.1:50052',
            device_id=1,
            proto_dump_file='logs/s2-p4runtime-requests.txt')

        s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name="s3",
            address='127.0.0.1:50053',
            device_id=2,
            proto_dump_file='logs/s3-p4runtime-requests.txt')

        s4 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name="s4",
            address='127.0.0.1:50054',
            device_id=3,
            proto_dump_file='logs/s4-p4runtime-requests.txt')

        # Send master arbitration update message from controller
        # master (required by P4Runtime before performing any other write operation)
        s1.MasterArbitrationUpdate()
        s2.MasterArbitrationUpdate()
        s3.MasterArbitrationUpdate()
        s4.MasterArbitrationUpdate()

        # Download p4 program to switch 
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                        bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForardingPipelineConfig on s1"

        s2.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                        bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForardingPipelineConfig on s2"

        s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                        bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForardingPipelineConfig on s3"

        s4.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                        bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForardingPipelineConfig on s4"

        # Set default drop action
        #setDefaultDrop(p4info_helper,ingress_sw=s1)
        #setDefaultDrop(p4info_helper,ingress_sw=s2)
        #setDefaultDrop(p4info_helper,ingress_sw=s3)
        #setDefaultDrop(p4info_helper,ingress_sw=s4)

        # Set forward rules
        # - s1 (MPLS Ingress)
        writeMplsIngressRules(p4info_helper,ingress_sw=s1,
            dst_ip_addr="10.0.4.4",port=2,label=1020)
        writeMplsEgressRules(p4info_helper,ingress_sw=s1,
            dst_eth_addr="00:00:00:00:01:01",port=1,dst_label=2111)

        # - s2 (MPLS Core)
        writeMplsCoreRules(p4info_helper,ingress_sw=s2,
            port=4,dst_label=1020,new_label=2030)
        writeMplsCoreRules(p4info_helper,ingress_sw=s2,
            port=3,dst_label=3020,new_label=2111)

        # - s3 (MPLS Core)
        writeMplsCoreRules(p4info_helper,ingress_sw=s3,
            port=3,dst_label=2030,new_label=3040)
        writeMplsCoreRules(p4info_helper,ingress_sw=s3,
            port=2,dst_label=4131,new_label=3020)

        # - s4 (MPLS Egress)
        writeMplsEgressRules(p4info_helper,ingress_sw=s4,
            dst_eth_addr="00:00:00:00:04:04",port=1,dst_label=3040)
        writeMplsIngressRules(p4info_helper,ingress_sw=s4,
            dst_ip_addr="10.0.1.1",port=4,label=4131)

        # read table entries
        readTableRules(p4info_helper, s1)
        readTableRules(p4info_helper, s2)
        readTableRules(p4info_helper, s3)
        readTableRules(p4info_helper, s4)

    except KeyboardInterrupt:
        # using ctrl + c to exit
        print "Shutting down."
    except grpc.RpcError as e:
        printGrpcError(e)

    # Then close all the connections
    ShutdownAllSwitchConnections()


if __name__ == '__main__':
    """ Simple P4 Controller
        Args:
            p4info:     P4 Program generated p4info file in txt format during compilation 
            bmv2-json:  P4 Program generated json file during compilation 
     """

    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    # Specified result which compile from P4 program
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
            type=str, action="store", required=False,
            default="./simple.p4info")
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
            type=str, action="store", required=False,
            default="./simple.json")
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print "\np4info file not found: %s\nPlease compile the target P4 program first." % args.p4info
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print "\nBMv2 JSON file not found: %s\nPlease compile the target P4 program first." % args.bmv2_json
        parser.exit(1)

    # Pass argument into main function
    main(args.p4info, args.bmv2_json)
