#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Licensed under the GNU General Public License Version 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

# Copyright (C) 2009-2013
#    Richard Hughes <richard@hughsie.com>
#

import os
import sys
import re
import fnmatch
import cairo

from application import Application
from package import Package

from PIL import Image, ImageOps
from gi.repository import GdkPixbuf, Gdk, GLib, Rsvg

class DesktopFile(Application):

    def resize_icon(self, icon, filename):

        # get ending
        ext = icon.rsplit('.', 1)[1]
        size = self.cfg.icon_size;
        min_size = self.cfg.min_icon_size;

        # use GDK to process XPM files
        gdk_exts = [ 'xpm', 'ico' ]
        if ext in gdk_exts:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon)
            if pixbuf.get_width() < min_size or pixbuf.get_height() < min_size:
                raise StandardError('Icon too small to process')
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon, size, size)
            pixbuf.savev(filename, "png", [], [])
            return

        # use PIL to resize PNG files
        pil_exts = [ 'png', 'gif' ]
        if ext in pil_exts:
            im = Image.open(icon)
            width, height = im.size
            if width < min_size or height < min_size:
                raise StandardError('Icon too small to process (' + str(width) + 'px)')

            # do not resize, just add a transparent border
            if width <= size and height <= size:
                bwidth = (size - width) / 2
                im = ImageOps.expand(im, border=bwidth)
                im.save(filename, 'png')
                return

            im = im.resize((size, size), Image.ANTIALIAS)
            im.save(filename, 'png')
            return

        # use RSVG to write PNG file
        rsvg_exts = [ 'svg' ]
        if ext in rsvg_exts:
            img = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            ctx = cairo.Context(img)
            handler = Rsvg.Handle.new_from_file(icon)
            ctx.scale(float(64) / handler.props.width, float(size) / handler.props.height)
            handler.render_cairo(ctx)
            img.write_to_png(filename)
            return
        return

    def write_appstream_icon(self, icon, filename):

        # we can handle these sorts of files
        supported_ext = [ '.png', '.svg', '.xpm' ]

        # remove any extension we recognise
        if not icon.startswith('/'):
            icon_split = icon.rsplit('.', 1)
            if len(icon_split) == 2:
                if '.' + icon_split[1] in supported_ext:
                    icon = icon_split[0]

        # fully qualified path
        icon_fullpath = './tmp/' + icon
        if os.path.exists(icon_fullpath):
            self.resize_icon(icon_fullpath, filename)
            return

        # hicolor apps
        icon_sizes = self.cfg.get_preferred_icon_sizes()
        for s in icon_sizes:
            for ext in supported_ext:
                icon_fullpath = './tmp/usr/share/icons/hicolor/' + s + '/apps/' + icon + ext
                if os.path.isfile(icon_fullpath):
                    self.resize_icon(icon_fullpath, filename)
                    return

        # pixmap
        for location in [ 'pixmaps', 'icons' ]:
            for ext in supported_ext:
                icon_fullpath = './tmp/usr/share/' + location + '/' + icon + ext
                if os.path.isfile(icon_fullpath):
                    self.resize_icon(icon_fullpath, filename)
                    return

        return

    def parse_file(self, f):

        config = GLib.KeyFile()
        config.load_from_file(f, GLib.KeyFileFlags.KEEP_TRANSLATIONS)

        icon_fullpath = None
        skip = False
        DG = GLib.KEY_FILE_DESKTOP_GROUP
        keys, _ = config.get_keys(DG)
        for k in keys:
            if k == GLib.KEY_FILE_DESKTOP_KEY_NO_DISPLAY and config.get_boolean(DG, k):
                print 'IGNORE\t', f, '\t', "not included in the menu"
                skip = True
                break
            elif k == GLib.KEY_FILE_DESKTOP_KEY_TYPE and \
                 config.get_string(DG, k) != GLib.KEY_FILE_DESKTOP_TYPE_APPLICATION:
                print 'IGNORE\t', f, '\t', "not an application"
                skip = True
                break
            elif k.startswith(GLib.KEY_FILE_DESKTOP_KEY_NAME):
                m = re.match(GLib.KEY_FILE_DESKTOP_KEY_NAME + '\[([^\]]+)\]', k)
                if m:
                    self.names[m.group(1)] = config.get_string(DG, k)
                else:
                    self.names['C'] = config.get_string(DG, k)
            elif k.startswith(GLib.KEY_FILE_DESKTOP_KEY_COMMENT):
                m = re.match(GLib.KEY_FILE_DESKTOP_KEY_COMMENT + '\[([^\]]+)\]', k)
                if m:
                    self.comments[m.group(1)] = config.get_string(DG, k)
                else:
                    self.comments['C'] = config.get_string(DG, k)
            elif k == GLib.KEY_FILE_DESKTOP_KEY_ICON:
                icon = config.get_string(DG, k)
                if icon:
                    self.icon = icon.strip()
            elif k == GLib.KEY_FILE_DESKTOP_KEY_CATEGORIES:
                self.categories = config.get_string_list(DG, k)
            elif k == 'Keywords':
                self.keywords = config.get_string_list(DG, k)
            elif k == 'MimeType':
                self.mimetypes = config.get_string_list(DG, k)
        if skip:
            return False

        # Do not include apps without a Name
        if not 'C' in self.names:
            print 'IGNORE\t', f, '\t', "no Name"
            return False

        # Do not include apps without a Comment
        if not 'C' in self.comments:
            print 'IGNORE\t', f, '\t', "no Comment"
            return False

        if not self.icon:
            print 'IGNORE\t', f, '\t', "Icon unspecified"
            return False

        # We blacklist some apps by categories
        blacklisted = False
        if self.categories:
            for c in self.categories:
                for b in self.cfg.get_category_blacklist():
                    if fnmatch.fnmatch(c, b):
                        print 'IGNORE\t', f, '\tcategory is blacklisted:', c
                        blacklisted = True
                        break
        if blacklisted:
            return False;

        # do we have to add any categories
        if self.categories:
            cats_to_add = self.cfg.get_category_extra_for_id(self.app_id)
            if cats_to_add:
                # check it's not been added upstream
                for cat in cats_to_add:
                    if cat in self.categories:
                        print 'WARNING\t' + app_id + ' now includes category ' + cat
                    else:
                        print 'INFO\tFor ' + app_id + ' manually adding category', cat
                self.categories.extend(cats_to_add)

        # check icon exists
        if self.icon not in self.cfg.get_stock_icons():
            icon_fullpath = './icons/' + self.app_id + '.png'
            try:
                self.write_appstream_icon(self.icon, icon_fullpath)
            except Exception as e:
                print 'IGNORE\t', f, '\t', "icon is corrupt:", icon, str(e)
                return False
            if not os.path.exists(icon_fullpath):
                print 'IGNORE\t', f, '\t', "icon does not exist:", icon
                return False

        return True

def main():
    pkg = Package(sys.argv[1])
    app = DesktopFile(pkg, None)
    app.app_id = 'test'
    app.names['C'] = 'test'
    app.comments['C'] = 'Test package'
    f = open('/tmp/test.xml', 'w')
    app.write(f)
    f.close()
    sys.exit(0)

if __name__ == "__main__":
    main()
