#pragma once
#include <QPainter>
#include <QLineF>
#include <QImage>
#include <QFontMetricsF>
#include <QFile>
#include <QSaveFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QMutex>
#include <QMutexLocker>
#include <QtEndian>
#include <cmath>
#include <cstring>
#include "camerapixelcopy.h"
#include "pcdemopairpolicy.h"
#ifdef Q_OS_LINUX
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#ifndef F_GET_SEALS
#define F_GET_SEALS 1034
#endif
#endif
struct PcDemoPair {QImage image;QJsonObject meta;QByteArray json,nonce;quint64 fid=0,ordinal=0,capture=0,ticks=0,firstRead=0;int pid=0,fd=-1;bool valid=false;};
struct PcDemoDrawState {QMutex mutex;PcDemoPair pair;bool inputValid=false,lastGeometry=false,lastCurrent=false,havePreparedAck=false;QJsonObject preparedAck;quint64 lastCopied=0,lastAckCopiedNs=0;QString lastAckStatus;};
inline PcDemoDrawState &pcDemoState(){static PcDemoDrawState s;return s;}
inline bool pcDemoU64(const QJsonValue &v,quint64 *out){if(!v.isDouble())return false;double d=v.toDouble();if(!std::isfinite(d)||d<0||d>9007199254740991.||std::floor(d)!=d)return false;*out=quint64(d);return true;}
inline bool pcDemoTicks(int pid,quint64 *ticks){QFile f(QStringLiteral("/proc/%1/stat").arg(pid));if(!f.open(QIODevice::ReadOnly))return false;QByteArray raw=f.read(8192);int at=raw.lastIndexOf(')');if(at<0)return false;QList<QByteArray> fields=raw.mid(at+2).simplified().split(' ');if(fields.size()<=19||fields[0]=="Z")return false;bool ok=false;*ticks=fields[19].toULongLong(&ok);return ok&&*ticks>0;}
inline pc_demo_pair_policy::Decision pcDemoPairDecision(const PcDemoPair &pair,bool inputValid,quint64 now){return pc_demo_pair_policy::evaluate(pair.valid,inputValid,pair.capture,pair.firstRead,now);}
inline bool pcDemoGeometryValid(const PcDemoPair &pair,bool inputValid,quint64 now){return pcDemoPairDecision(pair,inputValid,now).drawable;}
inline bool pcDemoReadPair(PcDemoPair *next,bool *unchanged){
#ifdef Q_OS_LINUX
 auto &s=pcDemoState();PcDemoPair old;{QMutexLocker lock(&s.mutex);old=s.pair;}
 const QString root=qEnvironmentVariable("MEDCOMM_PC_DEMO_ROOT");if(!root.startsWith("/run/gesture-pc-demo-"))return false;
 const QByteArray jsonName=(root+"/overlay_current.json").toLocal8Bit();int jfd=::open(jsonName.constData(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(jfd<0)return false;
 struct stat js{};bool jgood=::fstat(jfd,&js)==0&&S_ISREG(js.st_mode)&&js.st_uid==0&&js.st_nlink==1&&js.st_size>0&&js.st_size<=65536;
 QByteArray data;if(jgood){data.resize(int(js.st_size));jgood=::read(jfd,data.data(),data.size())==data.size();}::close(jfd);if(!jgood)return false;
 if(old.valid&&data==old.json){*next=old;*unchanged=true;return true;}
 QJsonParseError error;auto doc=QJsonDocument::fromJson(data,&error);if(error.error!=QJsonParseError::NoError||!doc.isObject())return false;const auto o=doc.object();
 if(o.value("version").toInt()!=1||o.value("session_id").toString()!=qEnvironmentVariable("MEDCOMM_PC_DEMO_SESSION_ID")||o.value("boot_id").toString()!=qEnvironmentVariable("MEDCOMM_PC_DEMO_BOOT_ID"))return false;
 quint64 fid=0,ordinal=0;if(!pcDemoU64(o.value("frame_id"),&fid)||!pcDemoU64(o.value("selected_ordinal"),&ordinal)||!ordinal)return false;
 bool captureOk=false;const quint64 capture=o.value("source_capture_ns").toString().toULongLong(&captureOk);if(!captureOk||!capture||capture>li_monotonic_ns())return false;
 if(old.valid&&(ordinal<=old.ordinal||fid<=old.fid||capture<=old.capture))return false;
 const auto body=o.value("body_points").toArray(),valid=o.value("body_valid").toArray();if(body.size()!=17||valid.size()!=17||o.value("hands").toArray().size()>2||o.value("person_boxes").toArray().size()>32)return false;
 if(!o.value("image_memfd").isObject())return false;const auto spec=o.value("image_memfd").toObject();quint64 pid64=0,fd64=0,bytes=0,header=0;
 if(!pcDemoU64(spec.value("bridge_pid"),&pid64)||pid64<2||pid64>2147483647||!pcDemoU64(spec.value("fd"),&fd64)||fd64>1048576||!pcDemoU64(spec.value("body_bytes"),&bytes)||bytes!=1152000||!pcDemoU64(spec.value("header_bytes"),&header)||header!=64||spec.value("pixel_format").toString()!="BGR888")return false;
 const int pid=int(pid64),fdnum=int(fd64);bool ticksOk=false;const QString ticksText=spec.value("bridge_start_ticks").toString();const quint64 expectedTicks=ticksText.toULongLong(&ticksOk);if(!ticksOk||!expectedTicks||QString::number(expectedTicks)!=ticksText)return false;
 const QByteArray nonceHex=spec.value("nonce").toString().toLatin1();if(nonceHex.size()!=32)return false;for(char c:nonceHex)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;const QByteArray nonce=QByteArray::fromHex(nonceHex);if(nonce.size()!=16)return false;
 if(old.valid&&(pid!=old.pid||expectedTicks!=old.ticks||nonce==old.nonce))return false;
 quint64 ticks=0;if(!pcDemoTicks(pid,&ticks)||ticks!=expectedTicks)return false;
 const QByteArray procDir=QStringLiteral("/proc/%1").arg(pid).toLocal8Bit();struct stat processStat{};if(::stat(procDir.constData(),&processStat)||processStat.st_uid!=0)return false;
 // /proc/PID/fd/N is deliberately a magic symlink: open it, then validate the OFD.
 const QByteArray fdName=QStringLiteral("/proc/%1/fd/%2").arg(pid).arg(fdnum).toLocal8Bit();int imageFd=::open(fdName.constData(),O_RDONLY|O_CLOEXEC);if(imageFd<0)return false;
 struct stat fs{};bool good=::fstat(imageFd,&fs)==0&&S_ISREG(fs.st_mode)&&fs.st_uid==0&&fs.st_size==1152064&&::fcntl(imageFd,F_GET_SEALS)==15;
 QByteArray raw;if(good){raw.resize(1152064);good=::pread(imageFd,raw.data(),raw.size(),0)==raw.size();}
 struct stat currentFd{};good=good&&::stat(fdName.constData(),&currentFd)==0&&currentFd.st_dev==fs.st_dev&&currentFd.st_ino==fs.st_ino&&currentFd.st_size==fs.st_size;::close(imageFd);
 if(!good||!pcDemoTicks(pid,&ticks)||ticks!=expectedTicks)return false;
 const QByteArray magic=QByteArray("PCFRM01",7)+char(0);if(raw.left(8)!=magic||raw.mid(40,16)!=nonce||raw.mid(56,8)!=QByteArray(8,char(0)))return false;
 const auto load=[&](int at){return qFromLittleEndian<quint64>(reinterpret_cast<const uchar*>(raw.constData()+at));};
 if(load(8)!=fid||load(16)!=ordinal||load(24)!=capture||load(32)!=bytes)return false;
 QImage image(800,480,QImage::Format_RGB888);if(image.isNull())return false;medcomm_copy_bgr_to_rgb(image.bits(),reinterpret_cast<const unsigned char*>(raw.constData()+64),800*480);
 next->image=image;next->meta=o;next->json=data;next->fid=fid;next->ordinal=ordinal;next->capture=capture;next->pid=pid;next->fd=fdnum;next->ticks=expectedTicks;next->nonce=nonce;next->firstRead=li_monotonic_ns();next->valid=true;*unchanged=false;return true;
#else
 Q_UNUSED(next);Q_UNUSED(unchanged);return false;
#endif
}
// Return1 only for a new authenticated source pair,2 for geometry clear/restore.
// A same-source clear may reblit its sealed image, never increments source count.
inline int pcDemoPollPair(QImage *image,quint64 *fid){
 PcDemoPair next;bool unchanged=false;const bool good=pcDemoReadPair(&next,&unchanged);auto &s=pcDemoState();QMutexLocker lock(&s.mutex);
 const bool previousInput=s.inputValid;if(good&&!unchanged)s.pair=next;s.inputValid=good;const auto decision=pcDemoPairDecision(s.pair,s.inputValid,li_monotonic_ns());const bool geometry=decision.drawable;const bool transition=geometry!=s.lastGeometry||decision.currentSourceValid!=s.lastCurrent||previousInput!=good;s.lastGeometry=geometry;s.lastCurrent=decision.currentSourceValid;
 const int action=good&&!unchanged?1:transition?2:0;if(action&&s.pair.valid){*image=s.pair.image;*fid=s.pair.fid;return action;}return 0;
}
inline bool pcDemoDraw(QPainter *p,const QRectF &target,bool prepared=false,bool backgroundReady=false,bool batch=false){
 const QString root=qEnvironmentVariable("MEDCOMM_PC_DEMO_ROOT");if(root.isEmpty())return false;auto &state=pcDemoState();PcDemoPair pair;bool inputValid=false;{QMutexLocker lock(&state.mutex);pair=state.pair;inputValid=state.inputValid;}
 const quint64 now=li_monotonic_ns();const auto decision=pcDemoPairDecision(pair,inputValid,now);const bool geometry=decision.drawable;const auto o=pair.meta;
 QJsonObject ack{{"status","DEMO_OVERLAY_EMPTY_OR_STALE"},{"session_id",qEnvironmentVariable("MEDCOMM_PC_DEMO_SESSION_ID")},{"boot_id",qEnvironmentVariable("MEDCOMM_PC_DEMO_BOOT_ID")},{"selected_ordinal",0},{"source_frame_id",pair.valid?QJsonValue(double(pair.fid)):QJsonValue(QJsonValue::Null)},{"image_source_frame_id",pair.valid?QJsonValue(double(pair.fid)):QJsonValue(QJsonValue::Null)},{"image_selected_ordinal",double(pair.ordinal)},{"source_frame_pairing_verified",pair.valid},{"source_capture_ns",pair.valid?QString::number(pair.capture):QString()},{"person_boxes",0},{"hands",0},{"body_valid_points",0},{"current_source_valid",false},{"NN_RUN",0},{"render_on_board",true}};
 // Both Qt scene and direct framebuffer start from the same immutable pair image.
 if(pair.valid&&!backgroundReady)p->drawImage(target,pair.image);
 if(geometry){
 const auto body=o.value("body_points").toArray(),bodyValid=o.value("body_valid").toArray(),hands=o.value("hands").toArray(),persons=o.value("person_boxes").toArray();
 const qreal sx=target.width()/800.,sy=target.height()/480.;auto point=[&](const QJsonValue &v,QPointF *out){auto a=v.toArray();if(a.size()!=2||!a[0].isDouble()||!a[1].isDouble())return false;double x=a[0].toDouble(),y=a[1].toDouble();if(!std::isfinite(x)||!std::isfinite(y)||x<0||x>=800||y<0||y>=480)return false;*out=QPointF(x*sx,y*sy);return true;};
 p->save();p->setClipRect(target);p->translate(target.topLeft());QFont font=p->font();font.setPixelSize(qMax(13,qRound(15*qMin(sx,sy))));font.setBold(true);p->setFont(font);
 auto box=[&](const QJsonArray &b,const QColor &color,const QString &label){
  if(b.size()!=4)return false;for(const auto &v:b)if(!v.isDouble()||!std::isfinite(v.toDouble()))return false;double x0=b[0].toDouble(),y0=b[1].toDouble(),x1=b[2].toDouble(),y1=b[3].toDouble();if(x0<0||y0<0||x1>800||y1>480||x1<=x0||y1<=y0)return false;
  const QRectF r(x0*sx,y0*sy,(x1-x0)*sx,(y1-y0)*sy);p->setBrush(Qt::NoBrush);p->setPen(QPen(QColor("#071318"),6));p->drawRect(r);p->setPen(QPen(color,3));p->drawRect(r);
  const QFontMetricsF metrics(p->font());const qreal th=metrics.height()+6,tw=qMin(target.width(),metrics.horizontalAdvance(label)+10),tx=qMin(r.left(),qMax(qreal(0),target.width()-tw)),ty=r.top()>=th?r.top()-th:r.top();const QRectF text(tx,ty,tw,th);p->fillRect(text,QColor(0,0,0,200));p->setPen(QColor("#FFFFFF"));p->drawText(text,Qt::AlignCenter,label);return true;
 };
 int personCount=0,handCount=0,bodyCount=0;const auto scores=o.value("person_scores").toArray();for(int i=0;i<persons.size();++i){QString label=QStringLiteral("person");if(i<scores.size()&&scores[i].isDouble()){const double score=scores[i].toDouble();if(std::isfinite(score)&&score>=0&&score<=1)label+=QStringLiteral(" %1").arg(score,0,'f',2);}if(box(persons[i].toArray(),QColor("#D44848"),label))++personCount;}
 QPointF bp[17];bool bv[17]={false};for(int i=0;i<17;++i){bv[i]=bodyValid[i].isBool()&&bodyValid[i].toBool()&&point(body[i],&bp[i]);if(bv[i])++bodyCount;}
 static const unsigned char be[][2]={{5,6},{5,7},{7,9},{6,8},{8,10},{5,11},{6,12},{11,12},{11,13},{13,15},{12,14},{14,16}};
 if(batch){QLineF lines[12];int n=0;for(const auto &e:be)if(bv[e[0]]&&bv[e[1]])lines[n++]=QLineF(bp[e[0]],bp[e[1]]);
  for(int pass=0;pass<2;++pass){p->setPen(QPen(pass?QColor("#35FF48"):QColor("#071318"),pass?4:7,Qt::SolidLine,Qt::RoundCap));p->drawLines(lines,n);}
 }else{ for(int pass=0;pass<2;++pass){p->setPen(QPen(pass?QColor("#35FF48"):QColor("#071318"),pass?4:7,Qt::SolidLine,Qt::RoundCap));for(const auto &e:be)if(bv[e[0]]&&bv[e[1]])p->drawLine(bp[e[0]],bp[e[1]]);}
 }
 p->setPen(QPen(QColor("#071318"),2));p->setBrush(QColor("#35FF48"));for(int i=0;i<17;++i)if(bv[i])p->drawEllipse(bp[i],5,5);
 static const unsigned char he[][2]={{0,1},{1,2},{2,3},{3,4},{0,5},{5,6},{6,7},{7,8},{5,9},{9,10},{10,11},{11,12},{9,13},{13,14},{14,15},{15,16},{13,17},{0,17},{17,18},{18,19},{19,20}};
 for(const auto &value:hands){
  auto hand=value.toObject();const auto pts=hand.value("points").toArray(),valid=hand.value("valid").toArray();if(pts.size()!=21||valid.size()!=21)continue;QPointF hp[21];bool hv[21]={false};int count=0;for(int i=0;i<21;++i){hv[i]=valid[i].isBool()&&valid[i].toBool()&&point(pts[i],&hp[i]);if(hv[i])++count;}if(!count)continue;
  const QString side=hand.value("side").toString();const QString requestedColorSide=hand.value("color_side").toString();const QString colorSide=(requestedColorSide=="Left"||requestedColorSide=="Right")?requestedColorSide:side;const QColor color=colorSide=="Right"?QColor("#FBD26A"):QColor("#01847F");QString label=(side=="Left"||side=="Right"?side:QStringLiteral("Hand"))+QStringLiteral(" 21pt");if(count<21)label+=QStringLiteral(" (%1/21)").arg(count);
  if(hand.value("whole_hand_presence").isDouble()){const double presence=hand.value("whole_hand_presence").toDouble();if(std::isfinite(presence)&&presence>=0&&presence<=1)label+=QStringLiteral(" p=%1").arg(presence,0,'f',3);}
  box(hand.value("box").toArray(),color,label);
  if(batch){QLineF lines[21];int n=0;for(const auto &e:he)if(hv[e[0]]&&hv[e[1]])lines[n++]=QLineF(hp[e[0]],hp[e[1]]);
   for(int pass=0;pass<2;++pass){p->setPen(QPen(pass?color:QColor("#071318"),pass?3:6,Qt::SolidLine,Qt::RoundCap));p->drawLines(lines,n);}
  }else{  for(int pass=0;pass<2;++pass)for(const auto &e:he)if(hv[e[0]]&&hv[e[1]]){p->setPen(QPen(pass?color:QColor("#071318"),pass?3:6,Qt::SolidLine,Qt::RoundCap));p->drawLine(hp[e[0]],hp[e[1]]);}
  }
  p->setPen(QPen(QColor("#071318"),1.5));p->setBrush(color);for(int i=0;i<21;++i)if(hv[i])p->drawEllipse(hp[i],3.5,3.5);++handCount;
 }
 const auto aux=o.value("body_aux").toArray();for(const auto &value:aux){const auto a=value.toObject();const QString name=a.value("name").toString();if((name!="FOREHEAD"&&name!="CHEST")||!a.value("valid").isBool()||!a.value("valid").toBool())continue;QPointF pos;if(!point(a.value("point"),&pos))continue;
  p->setPen(QPen(QColor("#071318"),2));p->setBrush(QColor("#CE73FF"));p->drawEllipse(pos,5,5);const QPointF labelAt=pos+QPointF(8,-6);const QString label=name+"*";p->setPen(QColor("#071318"));p->drawText(labelAt+QPointF(1,1),label);p->setPen(QColor("#FFFFFF"));p->drawText(labelAt,label);
 }

 p->restore();ack=QJsonObject{{"status","CURRENT_PC_COORDINATES_DRAWN_ON_NAV"},{"current_source_valid",true},{"boot_id",o.value("boot_id")},{"session_id",o.value("session_id")},{"source_frame_id",o.value("frame_id")},{"image_source_frame_id",double(pair.fid)},{"image_selected_ordinal",double(pair.ordinal)},{"source_frame_pairing_verified",true},{"selected_ordinal",o.value("selected_ordinal")},{"source_capture_ns",QString::number(pair.capture)},{"source_age_ms",double(now-pair.capture)/1000000.},{"person_boxes",personCount},{"hands",handCount},{"body_valid_points",bodyCount},{"body_and_hands_missing_never_filled",true},{"NN_RUN",0},{"render_on_board",true}};
 }
 ack.insert("source_fresh",decision.sourceFresh);ack.insert("current_source_valid",geometry&&decision.currentSourceValid);ack.insert("retained_same_source_pair",geometry&&decision.retained);ack.insert("geometry_drawn",geometry);ack.insert("input_read_valid",inputValid);ack.insert("pair_first_read_ns",QString::number(pair.firstRead));ack.insert("display_policy_reason",QString::fromLatin1(decision.reason));ack.insert("source_fresh_limit_ms",750);ack.insert("pair_hold_limit_ms",1000);ack.insert("absolute_source_limit_ms",2000);ack.insert("pair_display_age_ms",pair.firstRead&&now>=pair.firstRead?double(now-pair.firstRead)/1000000.:0.);if(pair.valid&&now>=pair.capture)ack.insert("source_age_ms",double(now-pair.capture)/1000000.);if(geometry&&decision.retained)ack.insert("status","RETAINED_SAME_SOURCE_PAIR_COORDINATES_DRAWN_ON_NAV");
 if(prepared){QMutexLocker lock(&state.mutex);state.preparedAck=ack;state.havePreparedAck=true;}return true;
}
inline void pcDemoCopied(quint64 copied,quint32 cameraSequence,quint64 prepareBegin=0,quint64 prepareDone=0,bool neonCopy=false){
 auto &s=pcDemoState();QJsonObject ack;{QMutexLocker lock(&s.mutex);if(!s.havePreparedAck)return;ack=s.preparedAck;s.havePreparedAck=false;}
 const QString root=qEnvironmentVariable("MEDCOMM_PC_DEMO_ROOT");if(!root.startsWith("/run/gesture-pc-demo-"))return;
 // Re-evaluate diagnostic freshness at actual framebuffer-copy completion.
 const quint64 capture=ack.value("source_capture_ns").toString().toULongLong(),firstRead=ack.value("pair_first_read_ns").toString().toULongLong();const bool drawn=ack.value("geometry_drawn").toBool();const auto decision=pc_demo_pair_policy::evaluate(ack.value("source_frame_pairing_verified").toBool(),ack.value("input_read_valid").toBool(),capture,firstRead,copied);ack.insert("source_fresh",decision.sourceFresh);ack.insert("current_source_valid",drawn&&decision.currentSourceValid);ack.insert("retained_same_source_pair",drawn&&!decision.currentSourceValid);ack.insert("display_policy_reason_at_copy",QString::fromLatin1(decision.reason));ack.insert("retention_deadline_crossed_during_copy",drawn&&!decision.drawable);if(capture&&copied>=capture)ack.insert("source_age_at_copy_ms",double(copied-capture)/1000000.);if(firstRead&&copied>=firstRead)ack.insert("pair_display_age_at_copy_ms",double(copied-firstRead)/1000000.);if(drawn&&!decision.currentSourceValid)ack.insert("status","RETAINED_SAME_SOURCE_PAIR_COORDINATES_DRAWN_ON_NAV");
 const quint64 ordinal=quint64(ack.value("image_selected_ordinal").toDouble());const QString status=ack.value("status").toString();
 if(ordinal==s.lastCopied&&status==s.lastAckStatus&&s.lastAckCopiedNs&&copied>=s.lastAckCopiedNs&&copied-s.lastAckCopiedNs<500000000ULL)return;
 ack.insert("rgb_swap_method",qEnvironmentVariableIntValue("MEDCOMM_SWAP_NEON")==1?"neon16":"qt");
 ack.insert("render_method",qEnvironmentVariableIntValue("MEDCOMM_RENDER_FAST")==1?"copied_background_batched_lines":"original");ack.insert("render_equivalence_verified",qEnvironmentVariableIntValue("MEDCOMM_RENDER_VERIFY")==1);
 ack.insert("image_prepare_ns",QString::number(prepareDone-prepareBegin));ack.insert("framebuffer_write_ns",QString::number(copied-prepareDone));ack.insert("framebuffer_copy_method",neonCopy?"neon64":"libc_memcpy");
 ack.insert("framebuffer_copy_done_ns",QString::number(copied));ack.insert("camera_preview_sequence",double(cameraSequence));ack.insert("framebuffer_copy_only",true);ack.insert("per_frame_two_vblank_latency_claimed",false);
 QSaveFile f(root+"/overlay_draw_ack.json");bool committed=false;if(f.open(QIODevice::WriteOnly)){const QByteArray data=QJsonDocument(ack).toJson(QJsonDocument::Compact);if(f.write(data)==data.size())committed=f.commit();else f.cancelWriting();}
 if(committed){s.lastCopied=ordinal;s.lastAckCopiedNs=copied;s.lastAckStatus=status;}else QFile::remove(root+"/overlay_draw_ack.json");
}
