#pragma once
#include <QByteArray>
#include <QCryptographicHash>
#include <QString>
#ifdef Q_OS_LINUX
#include <dlfcn.h>
#endif
// SHA256 bytes remain mandatory. OpenSSL selection fails closed if unavailable.
inline QByteArray v18Sha256(const QByteArray &bytes, const QString &backend) {
 if (backend == QStringLiteral("qt"))
  return QCryptographicHash::hash(bytes,QCryptographicHash::Sha256);
#ifdef Q_OS_LINUX
 if (backend == QStringLiteral("openssl")) {
  using Fn = unsigned char*(*)(const unsigned char*,size_t,unsigned char*);
  static void *library=dlopen("/usr/lib/libcrypto.so.1.1",RTLD_NOW|RTLD_LOCAL);
  static Fn sha=library?reinterpret_cast<Fn>(dlsym(library,"SHA256")):nullptr;
  if (!sha) return QByteArray();
  QByteArray digest(32,'\0');
  if (!sha(reinterpret_cast<const unsigned char*>(bytes.constData()),size_t(bytes.size()),reinterpret_cast<unsigned char*>(digest.data())))return QByteArray();
  return digest;
 }
#endif
 return QByteArray();
}
