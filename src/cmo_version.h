#ifndef CMO_VERSION_H
#define CMO_VERSION_H

#include "version.h"

/* Cache-Me-Outside build marker.
 *
 * VALKEY_VERSION stays a strict major.minor.patch string. Replication parses
 * it with version2num(), which rejects any other shape, and the module API
 * tests compare INFO valkey_version to that numeric form. The fork marker is
 * reported separately so existing Redis and Valkey clients keep working. */
#define CMO_VERSION_SUFFIX "-cmo"
#define CMO_VERSION VALKEY_VERSION CMO_VERSION_SUFFIX

#endif
