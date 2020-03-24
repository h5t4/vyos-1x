# Copyright 2020 VyOS maintainers and contributors <maintainers@vyos.io>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library.  If not, see <http://www.gnu.org/licenses/>.

import os
import jinja2

from vyos.ifconfig.control import Control

template_v4 = """
# generated by ifconfig.py
option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
timeout 60;
retry 300;

interface "{{ intf }}" {
    send host-name "{{ hostname }}";
    {% if client_id -%}
    send dhcp-client-identifier "{{ client_id }}";
    {% endif -%}
    {% if vendor_class_id -%}
    send vendor-class-identifier "{{ vendor_class_id }}";
    {% endif -%}
    request subnet-mask, broadcast-address, routers, domain-name-servers,
        rfc3442-classless-static-routes, domain-name, interface-mtu;
    require subnet-mask;
}

"""

template_v6 = """
# generated by ifconfig.py
interface "{{ intf }}" {
    request routers, domain-name-servers, domain-name;
}

"""

class DHCP (Control):
    client_base = r'/var/lib/dhcp/dhclient_'

    def __init__ (self, ifname):
        # per interface DHCP config files
        self._dhcp = {
            4: {
                'ifname': ifname,
                'conf': self.client_base + ifname + '.conf',
                'pid':  self.client_base + ifname + '.pid',
                'lease': self.client_base + ifname + '.leases',
                'options': {
                    'intf': ifname,
                    'hostname': '',
                    'client_id': '',
                    'vendor_class_id': ''
                },
            },
            6: {
                'ifname': ifname,
                'conf': self.client_base + ifname + '.v6conf',
                'pid':  self.client_base + ifname + '.v6pid',
                'lease': self.client_base + ifname + '.v6leases',
                'accept_ra': f'/proc/sys/net/ipv6/conf/{ifname}/accept_ra',
                'options': {
                    'intf': ifname,
                    'dhcpv6_prm_only': False,
                    'dhcpv6_temporary': False
                },
            },
        }

    def get_dhcp_options(self):
        """
        Return dictionary with supported DHCP options.

        Dictionary should be altered and send back via set_dhcp_options()
        so those options are applied when DHCP is run.
        """
        return self._dhcp[4]['options']

    def set_dhcp_options(self, options):
        """
        Store new DHCP options used by next run of DHCP client.
        """
        self._dhcp[4]['options'] = options

    def get_dhcpv6_options(self):
        """
        Return dictionary with supported DHCPv6 options.

        Dictionary should be altered and send back via set_dhcp_options()
        so those options are applied when DHCP is run.
        """
        return self._dhcp[6]['options']

    def set_dhcpv6_options(self, options):
        """
        Store new DHCP options used by next run of DHCP client.
        """
        self._dhcp[6]['options'] = options

    # replace dhcpv4/v6 with systemd.networkd?
    def _set_dhcp(self):
        """
        Configure interface as DHCP client. The dhclient binary is automatically
        started in background!

        Example:

        >>> from vyos.ifconfig import Interface
        >>> j = Interface('eth0')
        >>> j.set_dhcp()
        """

        dhcp = self.get_dhcp_options()
        if not dhcp['hostname']:
            # read configured system hostname.
            # maybe change to vyos hostd client ???
            with open('/etc/hostname', 'r') as f:
                dhcp['hostname'] = f.read().rstrip('\n')

        # render DHCP configuration
        tmpl = jinja2.Template(template_v4)
        dhcp_text = tmpl.render(dhcp)
        with open(self._dhcp[4]['conf'], 'w') as f:
            f.write(dhcp_text)

        cmd = 'start-stop-daemon'
        cmd += ' --start'
        cmd += ' --oknodo'
        cmd += ' --quiet'
        cmd += ' --pidfile {pid}'
        cmd += ' --exec /sbin/dhclient'
        cmd += ' --'
        # now pass arguments to dhclient binary
        cmd += ' -4 -nw -cf {conf} -pf {pid} -lf {lease} {ifname}'
        return self._cmd(cmd.format(**self._dhcp[4]))

    def _del_dhcp(self):
        """
        De-configure interface as DHCP clinet. All auto generated files like
        pid, config and lease will be removed.

        Example:

        >>> from vyos.ifconfig import Interface
        >>> j = Interface('eth0')
        >>> j.del_dhcp()
        """
        if not os.path.isfile(self._dhcp[4]['pid']):
            self._debug_msg('No DHCP client PID found')
            return None

		# with open(self._dhcp[4]['pid'], 'r') as f:
		# 	pid = int(f.read())

        # stop dhclient, we need to call dhclient and tell it should release the
        # aquired IP address. tcpdump tells me:
        # 172.16.35.103.68 > 172.16.35.254.67: [bad udp cksum 0xa0cb -> 0xb943!] BOOTP/DHCP, Request from 00:50:56:9d:11:df, length 300, xid 0x620e6946, Flags [none] (0x0000)
        #  Client-IP 172.16.35.103
        #  Client-Ethernet-Address 00:50:56:9d:11:df
        #  Vendor-rfc1048 Extensions
        #    Magic Cookie 0x63825363
        #    DHCP-Message Option 53, length 1: Release
        #    Server-ID Option 54, length 4: 172.16.35.254
        #    Hostname Option 12, length 10: "vyos"
        #
        cmd = '/sbin/dhclient -cf {conf} -pf {pid} -lf {lease} -r {ifname}'
        self._cmd(cmd.format(**self._dhcp[4]))

        # cleanup old config files
        for name in ('conf', 'pid', 'lease'):
            if os.path.isfile(self._dhcp[4][name]):
                os.remove(self._dhcp[4][name])

    def _set_dhcpv6(self):
        """
        Configure interface as DHCPv6 client. The dhclient binary is automatically
        started in background!

        Example:

        >>> from vyos.ifconfig import Interface
        >>> j = Interface('eth0')
        >>> j.set_dhcpv6()
        """
        dhcpv6 = self.get_dhcpv6_options()

        # better save then sorry .. should be checked in interface script
        # but if you missed it we are safe!
        if dhcpv6['dhcpv6_prm_only'] and dhcpv6['dhcpv6_temporary']:
            raise Exception(
                'DHCPv6 temporary and parameters-only options are mutually exclusive!')

        # render DHCP configuration
        tmpl = jinja2.Template(template_v6)
        dhcpv6_text = tmpl.render(dhcpv6)
        with open(self._dhcp[6]['conf'], 'w') as f:
            f.write(dhcpv6_text)

        # no longer accept router announcements on this interface
        self._write_sysfs(self._dhcp[6]['accept_ra'], 0)

        # assemble command-line to start DHCPv6 client (dhclient)
        cmd = 'start-stop-daemon'
        cmd += ' --start'
        cmd += ' --oknodo'
        cmd += ' --quiet'
        cmd += ' --pidfile {pid}'
        cmd += ' --exec /sbin/dhclient'
        cmd += ' --'
        # now pass arguments to dhclient binary
        cmd += ' -6 -nw -cf {conf} -pf {pid} -lf {lease}'
        # add optional arguments
        if dhcpv6['dhcpv6_prm_only']:
            cmd += ' -S'
        if dhcpv6['dhcpv6_temporary']:
            cmd += ' -T'
        cmd += ' {ifname}'

        return self._cmd(cmd.format(**self._dhcp[6]))

    def _del_dhcpv6(self):
        """
        De-configure interface as DHCPv6 clinet. All auto generated files like
        pid, config and lease will be removed.

        Example:

        >>> from vyos.ifconfig import Interface
        >>> j = Interface('eth0')
        >>> j.del_dhcpv6()
        """
        if not os.path.isfile(self._dhcp[6]['pid']):
            self._debug_msg('No DHCPv6 client PID found')
            return None

		# with open(self._dhcp[6]['pid'], 'r') as f:
		# 	pid = int(f.read())

        # stop dhclient
        cmd = 'start-stop-daemon'
        cmd += ' --start'
        cmd += ' --oknodo'
        cmd += ' --quiet'
        cmd += ' --pidfile {pid}'
        self._cmd(cmd.format(**self._dhcp[6]))

        # accept router announcements on this interface
        self._write_sysfs(self._dhcp[6]['accept_ra'], 1)

        # cleanup old config files
        for name in ('conf', 'pid', 'lease'):
            if os.path.isfile(self._dhcp[6][name]):
                os.remove(self._dhcp[6][name])

