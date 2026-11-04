#pragma once
#include "live_integer_frame.h"
#include "camerapixelcopy.h"
#include "framesha256.h"
#include <QCryptographicHash>
#include <QFile>
#include <QFileInfo>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QSaveFile>
#include <QVariant>
#include <QtEndian>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>
#include <cerrno>
#include <cstdio>
// Only the authenticated parent owns this 0700 session directory and atomic profile file.
inline bool v18ApplySessionProfile(const QString& root,int* pollMs,QByteArray* profileSha){
 if(!root.startsWith(QStringLiteral("/run/gesture-live-integer-hdmi-v18/")))return false;
 QFile f(root+QStringLiteral("/ui_profile.json"));if(!f.open(QIODevice::ReadOnly)||f.size()<=0||f.size()>1024)return false;
 const QByteArray bytes=f.readAll();QJsonParseError error;const auto doc=QJsonDocument::fromJson(bytes,&error);
 if(error.error!=QJsonParseError::NoError||!doc.isObject())return false;const auto c=doc.object();
 if(c.size()!=4||!c.value("session_id").isString()||c.value("session_id").toString()!=QFileInfo(root).fileName()||!c.value("hash_backend").isString()||!c.value("poll_ms").isDouble()||!c.value("cache_prepared").isBool())return false;
 const QString backend=c.value("hash_backend").toString();const double poll=c.value("poll_ms").toDouble();
 if((backend!=QStringLiteral("qt")&&backend!=QStringLiteral("openssl"))||poll<1||poll>33||poll!=double(int(poll)))return false;
 qputenv("MEDCOMM_V18_HASH_BACKEND",backend.toLatin1());qputenv("MEDCOMM_V18_CACHE_PREPARED",c.value("cache_prepared").toBool()?"1":"0");
 *pollMs=int(poll);*profileSha=QCryptographicHash::hash(bytes,QCryptographicHash::Sha256).toHex();return true;
}
struct LiveIntegerInfo {
 quint32 publication=0,source=0;quint64 capture=0,observed=0,inferred=0,published=0,acquired=0,semanticStart=0;
 QByteArray captureSha,logicalSha,compositeSha,metadataSha;QJsonObject metadata;
 quint64 pollEntered=0,previousPollEntered=0,readBegin=0,headerDone=0,pixelsReadDone=0,pixelHashDone=0,metadataHashDone=0,metadataDone=0,textReady=0,blitBegin=0,preparedDone=0,blitWriteBegin=0;
 quint64 keeperReceiveBegin=0,keeperReceiveDone=0,framebufferInitBegin=0,framebufferInitDone=0;
 quint32 previousFrameDuplicateBlits=0,pollIntervalMs=0;bool preparedCacheHit=false,configuredCachePrepared=false;QString hashBackend;QByteArray profileConfigSha;
};
inline bool v18ReadFrame(const QString& root,quint32 previous,QImage* image,LiveIntegerInfo* info){
 const quint64 readBegin=li_monotonic_ns();
 QFile f(root+QStringLiteral("/current.frame"));if(!f.open(QIODevice::ReadOnly))return false;
 QByteArray header=f.read(256);if(header.size()!=256)return false;
 auto u32=[&](int n){return qFromLittleEndian<quint32>(reinterpret_cast<const uchar*>(header.constData()+n));};
 auto u64=[&](int n){return qFromLittleEndian<quint64>(reinterpret_cast<const uchar*>(header.constData()+n));};
 if(u32(0)!=0x38464c56||u32(4)!=18||u32(8)!=256||u32(12)!=800||u32(16)!=480||u32(20)!=2400||!u32(24)||u32(24)==previous||u32(32)!=800*480*3||u32(36)!=1||u32(240)>16384||f.size()!=256+800*480*3+u32(240))return false;
 LiveIntegerInfo v;v.readBegin=readBegin;v.headerDone=li_monotonic_ns();v.publication=u32(24);v.source=u32(28);v.capture=u64(48);v.observed=u64(56);v.inferred=u64(72);v.published=u64(80);v.semanticStart=u64(88);
 if(!v.capture||v.observed<v.capture||v.inferred<v.observed||v.published<v.inferred)return false;
 const QByteArray pixels=f.read(800*480*3),meta=f.read(u32(240));if(pixels.size()!=800*480*3||meta.size()!=int(u32(240)))return false;
 v.pixelsReadDone=li_monotonic_ns();
 v.captureSha=header.mid(112,32).toHex();v.logicalSha=header.mid(144,32).toHex();v.compositeSha=header.mid(176,32).toHex();v.metadataSha=header.mid(208,32).toHex();
 v.hashBackend=qEnvironmentVariable("MEDCOMM_V18_HASH_BACKEND","qt");
 const QByteArray pixelDigest=v18Sha256(pixels,v.hashBackend);v.pixelHashDone=li_monotonic_ns();
 const QByteArray metadataDigest=v18Sha256(meta,v.hashBackend);v.metadataHashDone=li_monotonic_ns();
 if(pixelDigest.size()!=32||metadataDigest.size()!=32||pixelDigest.toHex()!=v.compositeSha||metadataDigest.toHex()!=v.metadataSha)return false;
 QJsonParseError error;auto doc=QJsonDocument::fromJson(meta,&error);if(error.error!=QJsonParseError::NoError||!doc.isObject())return false;v.metadata=doc.object();
 if(v.metadata.value(QStringLiteral("capture_pixels_sha256")).toString().toLatin1()!=v.captureSha||v.metadata.value(QStringLiteral("logical_pixels_sha256")).toString().toLatin1()!=v.logicalSha||v.metadata.value(QStringLiteral("identity")).toObject().value(QStringLiteral("frame_id")).toVariant().toULongLong()!=v.source)return false;
 v.metadataDone=li_monotonic_ns();
 QImage out(800,480,QImage::Format_RGB888);medcomm_copy_bgr_to_rgb(out.bits(),reinterpret_cast<const unsigned char*>(pixels.constData()),800*480);v.acquired=li_monotonic_ns();
 QPainter p(&out);p.fillRect(QRect(0,438,800,42),QColor(12,28,34));p.setPen(Qt::white);QFont font=p.font();font.setPixelSize(19);p.setFont(font);
 auto event=v.metadata.value(QStringLiteral("word_event")).toObject();const bool accepted=event.value(QStringLiteral("accepted_by_original_gate")).toBool(false);
 const QString message=event.isEmpty()?QStringLiteral("手语识别：%1").arg(v.metadata.value(QStringLiteral("TCN_state")).toString()):accepted?QStringLiteral("已确认：%1").arg(event.value(QStringLiteral("display_gesture")).toString(event.value(QStringLiteral("gesture")).toString())):QStringLiteral("未确认");
 auto comparison=v.metadata.value(QStringLiteral("semantic_profile_comparison")).toObject();
 if(!comparison.isEmpty()){
  font.setPixelSize(16);p.setFont(font);int line=0;
  for(const auto& name:comparison.keys()){
   auto item=comparison.value(name).toObject(),current=item.value(QStringLiteral("event")).toObject();
   const QString label=current.isEmpty()?item.value(QStringLiteral("state")).toString():current.value(QStringLiteral("accepted_by_original_gate")).toBool(false)?current.value(QStringLiteral("display_gesture")).toString():QStringLiteral("未确认");
   p.drawText(QRect(10,438+line*20,780,20),Qt::AlignVCenter,name+(name==QStringLiteral("fast80")?QStringLiteral(" 实验"):QString())+QStringLiteral("：")+label+QStringLiteral(" | 推理源帧 %1").arg(v.source));if(++line==2)break;
  }
 }else p.drawText(QRect(10,440,780,38),Qt::AlignVCenter,message+QStringLiteral("  | 推理源帧 %1").arg(v.source));
 p.end();v.textReady=li_monotonic_ns();*image=out;*info=v;return true;
}
inline int v18ReceiveKeeperFd(const QString& root){
 int sock=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0);if(sock<0)return-1;timeval bounded{2,0};if(setsockopt(sock,SOL_SOCKET,SO_RCVTIMEO,&bounded,sizeof bounded)||setsockopt(sock,SOL_SOCKET,SO_SNDTIMEO,&bounded,sizeof bounded)){close(sock);return-1;}sockaddr_un a{};a.sun_family=AF_UNIX;QByteArray path=(root+QStringLiteral("/keeper.sock")).toLocal8Bit();if(path.size()>=int(sizeof a.sun_path)){close(sock);return-1;}std::memcpy(a.sun_path,path.constData(),path.size()+1);
 if(connect(sock,reinterpret_cast<sockaddr*>(&a),sizeof a)||send(sock,"GETFD",5,MSG_NOSIGNAL)!=5){close(sock);return-1;}
 char bytes[64],control[CMSG_SPACE(sizeof(int))];iovec iov{bytes,sizeof bytes};msghdr m{};m.msg_iov=&iov;m.msg_iovlen=1;m.msg_control=control;m.msg_controllen=sizeof control;ssize_t n=recvmsg(sock,&m,MSG_CMSG_CLOEXEC);close(sock);if(n!=17||std::memcmp(bytes,"V18_DRM_SHARED_FD",17))return-1;
 for(cmsghdr*c=CMSG_FIRSTHDR(&m);c;c=CMSG_NXTHDR(&m,c))if(c->cmsg_level==SOL_SOCKET&&c->cmsg_type==SCM_RIGHTS&&c->cmsg_len==CMSG_LEN(sizeof(int))){int fd;std::memcpy(&fd,CMSG_DATA(c),sizeof fd);return fd;}return-1;
}
inline void v18Acknowledge(const QString& root,const LiveIntegerInfo& f,quint64 copied,int fd){
 li_scan_receipt scan{};li_scan_profile profile{};int rc=fd>=0?li_scan_after_copy_profile(fd,f.publication,150,&scan,&profile):-ENODEV;
 const quint64 scanReturned=li_monotonic_ns();
 QJsonObject r{{"version",18},{"publication",int(f.publication)},{"frame_id",double(f.source)},{"capture_sha256",QString::fromLatin1(f.captureSha)},{"logical_sha256",QString::fromLatin1(f.logicalSha)},{"composite_sha256",QString::fromLatin1(f.compositeSha)},{"metadata_sha256",QString::fromLatin1(f.metadataSha)},{"framebuffer_copy_ns",QString::number(copied)},{"capture_ns",QString::number(f.capture)},{"inferred_ns",QString::number(f.inferred)},{"copy_fence_ns",QString::number(scan.copy_fence_ns)},{"event1_ns",QString::number(scan.event1_ns)},{"event2_ns",QString::number(scan.event2_ns)},{"observed1_ns",QString::number(scan.observed1_ns)},{"observed2_ns",QString::number(scan.observed2_ns)},{"sequence1",double(scan.sequence1)},{"sequence2",double(scan.sequence2)},{"HDMI_irq_before",QString::number(scan.irq_before)},{"HDMI_irq_after",QString::number(scan.irq_after)},{"crtc_id",int(scan.crtc_id)},{"scan_verified",rc==0&&scan.verified},{"scan_error",rc},{"same_fb_atomic_commits",int(scan.same_fb_atomic_commits)},{"atomic_test_only_passed",bool(scan.atomic_test_only)},{"scan_scope",QStringLiteral("DRM driver DMA/vblank second-boundary endpoint")}};
 QJsonObject ui{{"poll_entered_ns",QString::number(f.pollEntered)},{"previous_poll_entered_ns",QString::number(f.previousPollEntered)},{"read_begin_ns",QString::number(f.readBegin)},{"header_done_ns",QString::number(f.headerDone)},{"pixels_read_done_ns",QString::number(f.pixelsReadDone)},{"pixel_hash_done_ns",QString::number(f.pixelHashDone)},{"metadata_hash_done_ns",QString::number(f.metadataHashDone)},{"metadata_done_ns",QString::number(f.metadataDone)},{"rgb_copy_done_ns",QString::number(f.acquired)},{"text_ready_ns",QString::number(f.textReady)},{"blit_begin_ns",QString::number(f.blitBegin)},{"prepared_done_ns",QString::number(f.preparedDone)},{"blit_write_begin_ns",QString::number(f.blitWriteBegin)},{"framebuffer_copy_done_ns",QString::number(copied)},{"scan_returned_ns",QString::number(scanReturned)},{"hash_backend",f.hashBackend},{"poll_interval_ms",int(f.pollIntervalMs)},{"previous_frame_duplicate_blits",int(f.previousFrameDuplicateBlits)},{"prepared_cache_hit",f.preparedCacheHit}};
 QJsonObject native{{"entered_ns",QString::number(profile.entered_ns)},{"topology_done_ns",QString::number(profile.topology_done_ns)},{"plane_request_done_ns",QString::number(profile.plane_request_done_ns)},{"irq_before_done_ns",QString::number(profile.irq_before_done_ns)},{"event1_done_ns",QString::number(profile.event1_done_ns)},{"event2_done_ns",QString::number(profile.event2_done_ns)},{"irq_after_done_ns",QString::number(profile.irq_after_done_ns)},{"release_done_ns",QString::number(profile.release_done_ns)}};
 ui.insert("keeper_receive_begin_ns",QString::number(f.keeperReceiveBegin));ui.insert("keeper_receive_done_ns",QString::number(f.keeperReceiveDone));ui.insert("framebuffer_init_begin_ns",QString::number(f.framebufferInitBegin));ui.insert("framebuffer_init_done_ns",QString::number(f.framebufferInitDone));
 ui.insert("profile_config_sha256",QString::fromLatin1(f.profileConfigSha));ui.insert("configured_cache_prepared",f.configuredCachePrepared);
 r.insert("ui_latency_profile",ui);r.insert("native_scan_profile",native);
 if(f.semanticStart)r.insert("semantic_start_capture_ns",QString::number(f.semanticStart));QSaveFile file(root+QStringLiteral("/display_ack.json"));if(file.open(QIODevice::WriteOnly)){file.write(QJsonDocument(r).toJson(QJsonDocument::Compact));file.commit();}
 const quint64 ackCommitted=li_monotonic_ns();
 std::fprintf(stderr,"V18_UI_PROFILE_ACK_COMMITTED source=%u publication=%u committed_ns=%llu\n",f.source,f.publication,(unsigned long long)ackCommitted);
 std::fprintf(stderr,"V18_DISPLAY_ENDPOINT source=%u publication=%u scan_verified=%u scan_error=%d sequence=%u,%u capture_ns=%llu fb_copy_ns=%llu endpoint_ns=%llu\n",f.source,f.publication,scan.verified,rc,scan.sequence1,scan.sequence2,(unsigned long long)f.capture,(unsigned long long)copied,(unsigned long long)scan.event2_ns);std::fflush(stderr);
}
